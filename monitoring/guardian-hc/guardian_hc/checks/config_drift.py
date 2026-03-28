import os


class ConfigDriftChecker:
    def __init__(self, config):
        self.config = config

    async def check(self) -> dict:
        drifts = []
        if not os.path.exists(self.config.compose_file):
            drifts.append({"item": "compose_file", "actual": "NOT FOUND"})
        alerts = self.config.alerts
        tf = (alerts.get("telegram") or {}).get("token_file", "")
        if tf and not os.path.exists(tf):
            drifts.append({"item": f"secret:{tf}", "actual": "MISSING"})
        elif tf and os.path.getsize(tf) == 0:
            drifts.append({"item": f"secret:{tf}", "actual": "EMPTY"})
        return {"drifts": drifts, "count": len(drifts), "status": "drift" if drifts else "ok"}
