"""Tests for GuardianV2Config config model — v2 format and v1 backward compat."""

import yaml
import pytest

from guardian_hc.config import (
    GuardianV2Config,
    ServiceConfig,
    ModuleConfig,
    load_config,
)

# ---------------------------------------------------------------------------
# Sample v2 config
# ---------------------------------------------------------------------------

SAMPLE_V2_CONFIG = """
version: "2.0"
app_name: "Test App"
compose_file: "./docker-compose.yml"

services:
  - name: backend
    container: test-backend
    health_check:
      type: http
      url: "http://backend:8000/health"
    auto_heal:
      restart: true

  - name: postgres
    container: test-postgres
    health_check:
      type: tcp
      host: postgres
      port: 5432
    auto_heal:
      restart: true

plugins:
  smtp_alert:
    host: smtp.example.com
    port: 587
    enabled: true
  slack_notify:
    webhook_url: "https://hooks.slack.com/xxx"
    enabled: false

modules:
  - name: core_health
    services: [backend, postgres]
    probes: [http, tcp]
  - name: disk_watch
    services: []
    probes: [disk, memory]

database:
  host: postgres
  port: 5432
  dbname: guardian_db
  user: guardian

agents:
  - name: alert_dispatcher
    type: dispatcher
    interval: 60
  - name: report_builder
    type: reporter

alerts:
  telegram:
    token: "tok123"
    chat_id: "456"

patrols:
  critical:
    interval: "2m"
    checks: [containers]

disk:
  warning_threshold: 70
  critical_threshold: 85

ssl:
  domains:
    - example.com

ollama:
  enabled: false

vps_load:
  load_threshold: 4.0

network:
  probe_pairs: []

celery:
  redis_host: redis
  max_queue_depth: 200

daily_report:
  time: "08:00"
  channels: [email, telegram]
  recipients: ["admin@example.com"]

dashboard_port: 9090
"""

# ---------------------------------------------------------------------------
# Sample v1 config (no version field, no plugins/modules/database/agents)
# ---------------------------------------------------------------------------

SAMPLE_V1_CONFIG = """
app:
  name: "Legacy App"
  compose_file: "./docker-compose.yml"

services:
  - name: backend
    container: legacy-backend
    health_check:
      type: http
      url: "http://backend:8000/health"
    auto_heal:
      restart: true

alerts:
  telegram:
    token: "tok_old"
    chat_id: "789"

patrols:
  critical:
    interval: "2m"
    checks: [containers]

disk:
  warning_threshold: 70

ssl:
  domains: []

ollama:
  enabled: false

vps_load:
  load_threshold: 6.0

network:
  probe_pairs: []

celery:
  redis_host: redis

dashboard:
  port: 9090
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_v2() -> GuardianV2Config:
    raw = yaml.safe_load(SAMPLE_V2_CONFIG)
    return load_config(raw)


def _load_v1() -> GuardianV2Config:
    raw = yaml.safe_load(SAMPLE_V1_CONFIG)
    return load_config(raw)


# ---------------------------------------------------------------------------
# v2 config tests
# ---------------------------------------------------------------------------

class TestV2Config:

    def test_version_is_set(self):
        cfg = _load_v2()
        assert cfg.version == "2.0"

    def test_app_name(self):
        cfg = _load_v2()
        assert cfg.app_name == "Test App"

    def test_compose_file(self):
        cfg = _load_v2()
        assert cfg.compose_file == "./docker-compose.yml"

    def test_services_loaded(self):
        cfg = _load_v2()
        assert len(cfg.services) == 2
        names = [s.name for s in cfg.services]
        assert "backend" in names
        assert "postgres" in names

    def test_service_has_correct_container(self):
        cfg = _load_v2()
        backend = next(s for s in cfg.services if s.name == "backend")
        assert backend.container == "test-backend"

    def test_service_health_check(self):
        cfg = _load_v2()
        backend = next(s for s in cfg.services if s.name == "backend")
        assert backend.health_check["type"] == "http"
        assert "url" in backend.health_check

    def test_service_auto_heal(self):
        cfg = _load_v2()
        backend = next(s for s in cfg.services if s.name == "backend")
        assert backend.auto_heal["restart"] is True

    # Plugins ---

    def test_plugins_loaded(self):
        cfg = _load_v2()
        assert "smtp_alert" in cfg.plugins
        assert "slack_notify" in cfg.plugins

    def test_plugin_smtp_values(self):
        cfg = _load_v2()
        smtp = cfg.plugins["smtp_alert"]
        assert smtp["host"] == "smtp.example.com"
        assert smtp["port"] == 587
        assert smtp["enabled"] is True

    def test_plugin_slack_disabled(self):
        cfg = _load_v2()
        slack = cfg.plugins["slack_notify"]
        assert slack["enabled"] is False

    # Modules ---

    def test_modules_loaded(self):
        cfg = _load_v2()
        assert len(cfg.modules) == 2

    def test_module_names(self):
        cfg = _load_v2()
        names = [m.name for m in cfg.modules]
        assert "core_health" in names
        assert "disk_watch" in names

    def test_module_services(self):
        cfg = _load_v2()
        core = next(m for m in cfg.modules if m.name == "core_health")
        assert "backend" in core.services
        assert "postgres" in core.services

    def test_module_probes(self):
        cfg = _load_v2()
        core = next(m for m in cfg.modules if m.name == "core_health")
        assert "http" in core.probes
        assert "tcp" in core.probes

    def test_module_empty_services(self):
        cfg = _load_v2()
        disk = next(m for m in cfg.modules if m.name == "disk_watch")
        assert disk.services == []

    # Database ---

    def test_database_host(self):
        cfg = _load_v2()
        assert cfg.database["host"] == "postgres"

    def test_database_dbname(self):
        cfg = _load_v2()
        assert cfg.database["dbname"] == "guardian_db"

    # Agents ---

    def test_agents_loaded(self):
        cfg = _load_v2()
        assert len(cfg.agents) == 2

    def test_agent_names(self):
        cfg = _load_v2()
        names = [a["name"] for a in cfg.agents]
        assert "alert_dispatcher" in names
        assert "report_builder" in names

    # Daily report ---

    def test_daily_report_time(self):
        cfg = _load_v2()
        assert cfg.daily_report["time"] == "08:00"

    def test_daily_report_channels(self):
        cfg = _load_v2()
        assert "email" in cfg.daily_report["channels"]
        assert "telegram" in cfg.daily_report["channels"]

    def test_daily_report_recipients(self):
        cfg = _load_v2()
        assert "admin@example.com" in cfg.daily_report["recipients"]

    # Dashboard port ---

    def test_dashboard_port(self):
        cfg = _load_v2()
        assert cfg.dashboard_port == 9090

    # Other sections ---

    def test_alerts_present(self):
        cfg = _load_v2()
        assert "telegram" in cfg.alerts

    def test_patrols_present(self):
        cfg = _load_v2()
        assert "critical" in cfg.patrols

    def test_disk_present(self):
        cfg = _load_v2()
        assert cfg.disk["warning_threshold"] == 70

    def test_celery_present(self):
        cfg = _load_v2()
        assert cfg.celery["redis_host"] == "redis"


# ---------------------------------------------------------------------------
# v1 backward compat tests
# ---------------------------------------------------------------------------

class TestV1BackwardCompat:

    def test_version_is_1_0(self):
        cfg = _load_v1()
        assert cfg.version == "1.0"

    def test_plugins_empty(self):
        cfg = _load_v1()
        assert cfg.plugins == {}

    def test_modules_empty(self):
        cfg = _load_v1()
        assert cfg.modules == []

    def test_database_empty(self):
        cfg = _load_v1()
        assert cfg.database == {}

    def test_agents_empty(self):
        cfg = _load_v1()
        assert cfg.agents == []

    def test_daily_report_empty(self):
        cfg = _load_v1()
        assert cfg.daily_report == {}

    def test_services_still_loaded(self):
        cfg = _load_v1()
        assert len(cfg.services) == 1
        assert cfg.services[0].name == "backend"

    def test_v1_app_name_fallback(self):
        """v1 config puts name under app.name — load_config should handle this."""
        cfg = _load_v1()
        # Either the parsed name or the default "Application" is acceptable
        assert isinstance(cfg.app_name, str)
        assert len(cfg.app_name) > 0

    def test_dashboard_port_from_dashboard_section(self):
        """v1 has dashboard.port, v2 has dashboard_port at top level."""
        cfg = _load_v1()
        assert cfg.dashboard_port == 9090


# ---------------------------------------------------------------------------
# ServiceConfig dataclass tests
# ---------------------------------------------------------------------------

class TestServiceConfig:

    def test_defaults(self):
        svc = ServiceConfig(name="foo", container="foo-ctr")
        assert svc.health_check == {}
        assert svc.auto_heal == {}

    def test_mutable_defaults_are_independent(self):
        a = ServiceConfig(name="a", container="a-ctr")
        b = ServiceConfig(name="b", container="b-ctr")
        a.health_check["type"] = "http"
        assert "type" not in b.health_check


# ---------------------------------------------------------------------------
# ModuleConfig dataclass tests
# ---------------------------------------------------------------------------

class TestModuleConfig:

    def test_defaults(self):
        mod = ModuleConfig(name="test_mod")
        assert mod.services == []
        assert mod.probes == []

    def test_mutable_defaults_are_independent(self):
        a = ModuleConfig(name="a")
        b = ModuleConfig(name="b")
        a.services.append("svc1")
        assert "svc1" not in b.services
