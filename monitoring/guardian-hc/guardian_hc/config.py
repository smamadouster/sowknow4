"""
Guardian HC v2 Config Model.

Parses a pre-loaded dict (from YAML) into typed dataclasses.
Supports both v1 (legacy, no version field) and v2 config formats.

No external dependencies — stdlib only (dataclasses, typing).
YAML parsing is done by the caller before calling load_config().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ServiceConfig:
    """Configuration for a single monitored service."""

    name: str
    container: str
    health_check: dict = field(default_factory=dict)
    auto_heal: dict = field(default_factory=dict)


@dataclass
class ModuleConfig:
    """Configuration for a guardian module (group of services + probes)."""

    name: str
    services: list[str] = field(default_factory=list)
    probes: list[str] = field(default_factory=list)


@dataclass
class GuardianV2Config:
    """Unified config for Guardian HC — supports both v1 and v2 YAML formats."""

    version: str
    app_name: str
    compose_file: str
    services: list[ServiceConfig]
    plugins: dict[str, dict]
    modules: list[ModuleConfig]
    database: dict
    agents: list[dict]
    alerts: dict
    patrols: dict
    disk: dict
    ssl: dict
    ollama: dict
    vps_load: dict
    network: dict
    celery: dict
    daily_report: dict
    dashboard_port: int = 9090


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_service(raw: dict) -> ServiceConfig:
    return ServiceConfig(
        name=raw.get("name", ""),
        container=raw.get("container", ""),
        health_check=raw.get("health_check") or {},
        auto_heal=raw.get("auto_heal") or {},
    )


def _parse_module(raw: dict) -> ModuleConfig:
    return ModuleConfig(
        name=raw.get("name", ""),
        services=list(raw.get("services") or []),
        probes=list(raw.get("probes") or []),
    )


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_config(raw: dict) -> GuardianV2Config:
    """Parse a raw YAML dict into a GuardianV2Config.

    Detects the config version via ``raw.get("version", "1.0")``.

    v2 format: has a top-level ``version`` key (e.g. "2.0"), plus
    ``plugins``, ``modules``, ``database``, ``agents``, ``daily_report``.

    v1 format: no ``version`` key; app metadata lives under ``app``;
    dashboard port lives under ``dashboard.port``.
    """

    version: str = str(raw.get("version", "1.0"))

    # ----- App name / compose file -----
    if "app_name" in raw:
        # v2 top-level keys
        app_name: str = str(raw["app_name"])
        compose_file: str = str(raw.get("compose_file", "./docker-compose.yml"))
    elif "app" in raw:
        # v1 nested under app:
        app_section: dict = raw.get("app") or {}
        app_name = str(app_section.get("name", "Application"))
        compose_file = str(app_section.get("compose_file", "./docker-compose.yml"))
    else:
        app_name = "Application"
        compose_file = "./docker-compose.yml"

    # ----- Services -----
    services: list[ServiceConfig] = [
        _parse_service(s) for s in (raw.get("services") or [])
    ]

    # ----- v2-only sections (empty defaults for v1) -----
    plugins: dict[str, dict] = {}
    raw_plugins: Any = raw.get("plugins")
    if isinstance(raw_plugins, dict):
        plugins = {k: dict(v) if isinstance(v, dict) else {} for k, v in raw_plugins.items()}

    modules: list[ModuleConfig] = [
        _parse_module(m) for m in (raw.get("modules") or [])
    ]

    database: dict = dict(raw.get("database") or {})
    agents: list[dict] = [dict(a) for a in (raw.get("agents") or [])]
    daily_report: dict = dict(raw.get("daily_report") or {})

    # ----- Shared sections (present in both v1 and v2) -----
    alerts: dict = dict(raw.get("alerts") or {})
    patrols: dict = dict(raw.get("patrols") or {})
    disk: dict = dict(raw.get("disk") or {})
    ssl: dict = dict(raw.get("ssl") or {})
    ollama: dict = dict(raw.get("ollama") or {})
    vps_load: dict = dict(raw.get("vps_load") or {})
    network: dict = dict(raw.get("network") or {})
    celery: dict = dict(raw.get("celery") or {})

    # ----- Dashboard port -----
    # v2: top-level ``dashboard_port``
    # v1: nested under ``dashboard.port``
    if "dashboard_port" in raw:
        dashboard_port: int = int(raw["dashboard_port"])
    elif "dashboard" in raw and isinstance(raw["dashboard"], dict):
        dashboard_port = int(raw["dashboard"].get("port", 9090))
    else:
        dashboard_port = 9090

    return GuardianV2Config(
        version=version,
        app_name=app_name,
        compose_file=compose_file,
        services=services,
        plugins=plugins,
        modules=modules,
        database=database,
        agents=agents,
        alerts=alerts,
        patrols=patrols,
        disk=disk,
        ssl=ssl,
        ollama=ollama,
        vps_load=vps_load,
        network=network,
        celery=celery,
        daily_report=daily_report,
        dashboard_port=dashboard_port,
    )
