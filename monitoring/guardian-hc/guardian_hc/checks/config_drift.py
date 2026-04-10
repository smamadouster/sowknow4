import os


class ConfigDriftChecker:
    def __init__(self, config):
        self.config = config

    async def check(self) -> dict:
        drifts = []
        # Support both GuardianConfig objects (attribute access) and plain dicts
        if isinstance(self.config, dict):
            compose_file = self.config.get("compose_file", "")
            alerts = self.config.get("alerts", {})
        else:
            compose_file = getattr(self.config, "compose_file", "")
            alerts = getattr(self.config, "alerts", {})
        if compose_file and not os.path.exists(compose_file):
            drifts.append({"item": "compose_file", "actual": "NOT FOUND"})
        tf = (alerts.get("telegram") or {}).get("token_file", "")
        if tf and not os.path.exists(tf):
            drifts.append({"item": f"secret:{tf}", "actual": "MISSING"})
        elif tf and os.path.getsize(tf) == 0:
            drifts.append({"item": f"secret:{tf}", "actual": "EMPTY"})
        return {"drifts": drifts, "count": len(drifts), "status": "drift" if drifts else "ok"}
