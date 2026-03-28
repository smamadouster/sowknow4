import asyncio
from datetime import datetime, timezone


class SslChecker:
    def __init__(self, config=None):
        c = config or {}
        self.domains = c.get("domains", [])
        self.critical_days = c.get("critical_days", 3)

    async def check(self) -> list[dict]:
        results = []
        for domain in self.domains:
            try:
                proc = await asyncio.create_subprocess_shell(
                    f"echo | openssl s_client -servername {domain} -connect {domain}:443 2>/dev/null | openssl x509 -noout -enddate",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
                output = stdout.decode().strip()
                if "notAfter=" in output:
                    from email.utils import parsedate_to_datetime
                    expiry = parsedate_to_datetime(output.split("notAfter=")[1].strip().replace("GMT", "+0000"))
                    days = (expiry - datetime.now(timezone.utc)).days
                    results.append({"domain": domain, "days_left": days, "needs_healing": days < self.critical_days})
            except Exception as e:
                results.append({"domain": domain, "error": str(e)[:100], "needs_healing": False})
        return results
