import asyncio


class DiskChecker:
    def __init__(self, config=None):
        c = config or {}
        self.warning = c.get("warning_threshold", 75)
        self.critical = c.get("critical_threshold", 85)

    async def check(self) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                "df", "/", "--output=pcent", stdout=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            usage = int(stdout.decode().strip().split("\n")[-1].strip().rstrip("%"))
            severity = "critical" if usage >= self.critical else "warning" if usage >= self.warning else "ok"
            return {"usage_pct": usage, "severity": severity, "needs_healing": usage >= self.warning}
        except Exception as e:
            return {"usage_pct": -1, "severity": "error", "error": str(e)[:200], "needs_healing": False}
