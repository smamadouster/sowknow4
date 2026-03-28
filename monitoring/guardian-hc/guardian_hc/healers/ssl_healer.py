import asyncio


class SslHealer:
    def __init__(self, config=None):
        self.auto_renew = (config or {}).get("auto_renew", True)

    async def heal(self, domain: str) -> dict:
        if not self.auto_renew:
            return {"healed": False, "error": "Auto-renew disabled in config"}
        try:
            proc = await asyncio.create_subprocess_shell(
                f"certbot renew --cert-name {domain} --force-renewal --quiet && nginx -s reload",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            return {
                "healed": proc.returncode == 0,
                "action": "certbot renew + nginx reload",
                "output": stdout.decode()[:200] if stdout else stderr.decode()[:200],
            }
        except Exception as e:
            return {"healed": False, "error": str(e)[:200]}
