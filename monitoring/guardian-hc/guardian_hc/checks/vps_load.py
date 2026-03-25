"""
Guardian HC -- VPS load average and steal time check.

Reads /proc/loadavg and /proc/stat to detect overloaded or noisy-neighbour
conditions on the shared Hostinger VPS.
"""

import asyncio


class VpsLoadChecker:
    def __init__(self, config: dict = None):
        cfg = config or {}
        self.load_threshold = cfg.get("load_threshold", 6.0)
        self.steal_threshold = cfg.get("steal_threshold", 20.0)

    async def check(self) -> list[dict]:
        results = []

        # Load average
        try:
            with open("/proc/loadavg") as f:
                parts = f.read().split()
                load1, load5, load15 = float(parts[0]), float(parts[1]), float(parts[2])
                results.append({
                    "type": "load_average",
                    "load1": load1, "load5": load5, "load15": load15,
                    "needs_healing": load5 > self.load_threshold,
                })
        except Exception as e:
            results.append({"type": "load_average", "error": str(e)[:200], "needs_healing": False})

        # Steal time (read /proc/stat twice with 1s gap)
        try:
            def _read_cpu():
                with open("/proc/stat") as f:
                    line = f.readline()  # cpu  user nice system idle iowait irq softirq steal
                    parts = line.split()
                    return [int(x) for x in parts[1:]]

            s1 = _read_cpu()
            await asyncio.sleep(1)
            s2 = _read_cpu()

            delta = [b - a for a, b in zip(s1, s2)]
            total = sum(delta)
            if total > 0 and len(delta) >= 8:
                steal_pct = (delta[7] / total) * 100
                results.append({
                    "type": "steal_time",
                    "steal_pct": round(steal_pct, 1),
                    "needs_healing": steal_pct > self.steal_threshold,
                })
        except Exception as e:
            results.append({"type": "steal_time", "error": str(e)[:200], "needs_healing": False})

        return results
