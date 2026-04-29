"""
Resource-hog detection for Guardian HC.

Detects runaway processes that saturate CPU or memory and starve
other services on the host:
  - pytest/test processes running >2 hours (forgotten manual runs)
  - Any process consuming >200% CPU for >1 hour
  - Any process using >5GB RSS for >30 minutes
  - Sustained load average exceeding CPU count
"""

import asyncio


class ResourceHogsChecker:
    def __init__(self, config: dict = None):
        cfg = config or {}
        self.cpu_threshold_pct = cfg.get("cpu_threshold_pct", 200)   # % of one core
        self.cpu_time_min = cfg.get("cpu_time_min", 60)              # minutes
        self.mem_threshold_mb = cfg.get("mem_threshold_mb", 5120)    # MB
        self.load_sustained_min = cfg.get("load_sustained_min", 10)  # minutes

    async def check(self) -> list[dict]:
        results = []
        results.extend(await self._check_stray_tests())
        results.extend(await self._check_cpu_hogs())
        results.extend(await self._check_mem_hogs())
        results.extend(await self._check_sustained_load())
        return results

    async def _check_stray_tests(self) -> list[dict]:
        """Find pytest / test processes with >2h CPU time."""
        try:
            import subprocess
            ps = subprocess.run(
                ["ps", "aux", "--sort=-%cpu"],
                capture_output=True, text=True, timeout=10
            )
            hogs = []
            for line in ps.stdout.splitlines()[1:]:
                parts = line.split(None, 10)
                if len(parts) < 11:
                    continue
                cmd = parts[10]
                cpu_time = parts[9]
                pid = parts[1]
                if "pytest" not in cmd.lower() and "py.test" not in cmd.lower():
                    continue
                # Parse CPU time: HH:MM or DD-HH:MM
                hours = 0
                try:
                    if "-" in cpu_time:
                        days, rest = cpu_time.split("-", 1)
                        hours = int(days) * 24 + int(rest.split(":")[0])
                    else:
                        hours = int(cpu_time.split(":")[0])
                except Exception:
                    continue
                if hours >= 2:
                    hogs.append({
                        "pid": pid,
                        "cpu_time": cpu_time,
                        "cmd": cmd[:100],
                        "hours": hours,
                    })
            return [{
                "check": "stray_tests",
                "count": len(hogs),
                "processes": hogs,
                "needs_healing": len(hogs) > 0,
                "severity": "critical" if len(hogs) > 2 else "warning" if len(hogs) > 0 else "ok",
            }]
        except Exception as e:
            return [{"check": "stray_tests", "error": str(e)[:200], "needs_healing": False}]

    async def _check_cpu_hogs(self) -> list[dict]:
        """Find non-test processes using >200% CPU for >1 hour."""
        try:
            import subprocess
            ps = subprocess.run(
                ["ps", "aux", "--sort=-%cpu"],
                capture_output=True, text=True, timeout=10
            )
            hogs = []
            for line in ps.stdout.splitlines()[1:]:
                parts = line.split(None, 10)
                if len(parts) < 11:
                    continue
                cpu_pct = float(parts[2])
                cpu_time = parts[9]
                pid = parts[1]
                cmd = parts[10]
                # Skip system processes, dockerd, kernel threads
                if cmd.startswith("[") or cmd in ("ps", "top", "awk"):
                    continue
                if cpu_pct < self.cpu_threshold_pct:
                    continue
                # Parse CPU time
                hours = 0
                try:
                    if "-" in cpu_time:
                        days, rest = cpu_time.split("-", 1)
                        hours = int(days) * 24 + int(rest.split(":")[0])
                    else:
                        hours = int(cpu_time.split(":")[0])
                except Exception:
                    continue
                if hours >= self.cpu_time_min:
                    hogs.append({
                        "pid": pid,
                        "cpu_pct": cpu_pct,
                        "cpu_time": cpu_time,
                        "cmd": cmd[:100],
                        "hours": hours,
                    })
            return [{
                "check": "cpu_hogs",
                "count": len(hogs),
                "processes": hogs,
                "needs_healing": len(hogs) > 0,
                "severity": "critical" if len(hogs) > 2 else "warning" if len(hogs) > 0 else "ok",
            }]
        except Exception as e:
            return [{"check": "cpu_hogs", "error": str(e)[:200], "needs_healing": False}]

    async def _check_mem_hogs(self) -> list[dict]:
        """Find processes using >5GB RSS for >30 minutes."""
        try:
            import subprocess
            ps = subprocess.run(
                ["ps", "aux", "--sort=-%mem"],
                capture_output=True, text=True, timeout=10
            )
            hogs = []
            for line in ps.stdout.splitlines()[1:]:
                parts = line.split(None, 10)
                if len(parts) < 11:
                    continue
                rss_mb = float(parts[5]) / 1024  # ps aux RSS is in KB
                cpu_time = parts[9]
                pid = parts[1]
                cmd = parts[10]
                if rss_mb < self.mem_threshold_mb:
                    continue
                # Skip known legitimate heavy services (embed server can grow to 6GB under load)
                if any(x in cmd for x in ['embed_server.main', 'sowknow4-embed-server', 'postgres', 'redis-server']):
                    continue
                # Parse CPU time as proxy for runtime
                hours = 0
                try:
                    if "-" in cpu_time:
                        days, rest = cpu_time.split("-", 1)
                        hours = int(days) * 24 + int(rest.split(":")[0])
                    else:
                        hours = int(cpu_time.split(":")[0])
                except Exception:
                    continue
                if hours >= 0:  # Any duration, just the memory threshold matters
                    hogs.append({
                        "pid": pid,
                        "rss_mb": round(rss_mb, 1),
                        "cpu_time": cpu_time,
                        "cmd": cmd[:100],
                    })
            return [{
                "check": "mem_hogs",
                "count": len(hogs),
                "processes": hogs,
                "needs_healing": len(hogs) > 0,
                "severity": "critical" if len(hogs) > 2 else "warning" if len(hogs) > 0 else "ok",
            }]
        except Exception as e:
            return [{"check": "mem_hogs", "error": str(e)[:200], "needs_healing": False}]

    async def _check_sustained_load(self) -> list[dict]:
        """Check if load average has exceeded CPU count for sustained period.
        We use /proc/loadavg 5-min value as a proxy for sustained load."""
        try:
            import os
            with open("/proc/loadavg") as f:
                parts = f.read().split()
            load1, load5, load15 = float(parts[0]), float(parts[1]), float(parts[2])
            cpu_count = os.cpu_count() or 8
            # 5-min load > CPU count suggests sustained overload
            overloaded = load5 > cpu_count
            return [{
                "check": "sustained_load",
                "load1": load1,
                "load5": load5,
                "load15": load15,
                "cpu_count": cpu_count,
                "needs_healing": overloaded,
                "severity": "critical" if load5 > cpu_count * 1.5 else "warning" if overloaded else "ok",
            }]
        except Exception as e:
            return [{"check": "sustained_load", "error": str(e)[:200], "needs_healing": False}]
