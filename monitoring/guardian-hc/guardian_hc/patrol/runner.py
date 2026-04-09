import asyncio
import structlog

logger = structlog.get_logger()


def _parse_interval(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    return int(s)


class PatrolRunner:
    def __init__(self, guardian):
        self.guardian = guardian
        self.patrols = guardian.config.patrols

    async def _run_patrol(self, name: str, level: str, interval_sec: int):
        logger.info(f"patrol.{name}.started", interval=interval_sec)
        while True:
            try:
                # v1 check cycle (existing behavior)
                result = await self.guardian.run_check_cycle(level)

                # v2 plugin checks
                if self.guardian._plugins:
                    plugin_results = await self.guardian.run_plugin_checks(level)
                    heal_results = await self.guardian.run_plugin_heals(plugin_results)
                    result["plugin_checks"] = len(plugin_results)
                    result["plugin_heals"] = len(heal_results)

                    # Run analysis on deep patrol
                    if level == "deep":
                        insights = await self.guardian.run_plugin_analysis()
                        result["insights"] = len(insights)
                        for insight in insights:
                            if insight.recommended_action and insight.recommended_action != "alert_only":
                                logger.info("guardian.preventive_action",
                                            insight=insight.summary,
                                            action=insight.recommended_action)

                healed = result.get("healed", 0)
                failed = result.get("failed", 0)
                if healed > 0 or failed > 0:
                    logger.info(f"patrol.{name}.complete", healed=healed, failed=failed)

                # Correlate events and send grouped alerts
                await self.guardian.correlator.process(result)
            except Exception as e:
                logger.error(f"patrol.{name}.error", error=str(e)[:200])
            await asyncio.sleep(interval_sec)

    async def run(self):
        tasks = []
        for name, cfg in self.patrols.items():
            interval = _parse_interval(cfg.get("interval", "10m"))
            level = name
            tasks.append(asyncio.create_task(self._run_patrol(name, level, interval)))
            logger.info("patrol.scheduled", name=name, interval=cfg.get("interval"), level=level)
        if tasks:
            await asyncio.gather(*tasks)
        else:
            logger.warning("patrol.none_configured")
            while True:
                await asyncio.sleep(60)
