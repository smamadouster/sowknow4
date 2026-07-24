"""Regression tests for the guardian DB-access fixes (2026-07-24).

Guards against the bugs that left the pipeline probes blind:
- psql ran as role "postgres" (does not exist on the live server)
- enum labels queried UPPERCASE while PG enum labels are lowercase
- unqualified table name while the table lives in schema "sowknow"
- psql errors swallowed into count=0 (probe always reported healthy)
- sentinel watching nonexistent queues instead of the real pipeline.* ones
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from guardian_hc.plugin import CheckContext
from guardian_hc.plugins.probes import ProbesPlugin
from guardian_hc.plugins.sentinel import SentinelPlugin


def _make_ctx(level: str = "standard") -> CheckContext:
    return CheckContext(patrol_level=level, config={}, services=[])


def _make_plugin() -> ProbesPlugin:
    return ProbesPlugin(config={
        "backend_url": "http://localhost:8000",
        "redis_host": "localhost",
        "redis_port": 6379,
        "nginx_url": "http://localhost:80",
    })


def _completed_proc(stdout: str = "0\n", returncode: int = 0, stderr: str = ""):
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


class TestPipelineCheckSql:
    def test_uses_sowknow_role_and_db(self):
        """Every psql call must authenticate as sowknow@sowknow (role postgres does not exist)."""
        plugin = _make_plugin()
        with patch("subprocess.run", return_value=_completed_proc()) as mock_run:
            asyncio.run(plugin._check_pipeline(_make_ctx()))
        for call in mock_run.call_args_list:
            cmd = call.args[0]
            assert "-U" in cmd and cmd[cmd.index("-U") + 1] == "sowknow"
            assert "-d" in cmd and cmd[cmd.index("-d") + 1] == "sowknow"

    def test_uses_lowercase_enum_and_qualified_table(self):
        """Enum labels are lowercase in PG; table lives in schema sowknow."""
        plugin = _make_plugin()
        with patch("subprocess.run", return_value=_completed_proc()) as mock_run:
            asyncio.run(plugin._check_pipeline(_make_ctx()))
        for call in mock_run.call_args_list:
            sql = call.args[0][-1]
            assert "status='running'" in sql
            assert "RUNNING" not in sql
            assert "sowknow.pipeline_stages" in sql

    def test_query_failure_is_loud_not_zero(self):
        """A failed psql must NOT be reported as 'no stuck stages'."""
        plugin = _make_plugin()
        err = _completed_proc(stdout="", returncode=2, stderr="FATAL: role does not exist")
        with patch("subprocess.run", return_value=err):
            result = asyncio.run(plugin._check_pipeline(_make_ctx()))
        assert result.status == "warning"
        assert "failed" in result.summary.lower()
        assert result.needs_healing is False

    def test_stuck_count_reported(self):
        plugin = _make_plugin()
        with patch("subprocess.run", return_value=_completed_proc("3\n")):
            result = asyncio.run(plugin._check_pipeline(_make_ctx()))
        assert result.status == "warning"
        assert result.needs_healing is True
        assert result.heal_hint == "requeue_stuck_docs"


class TestPipelineOrphanedSql:
    def test_query_failure_is_loud(self):
        plugin = _make_plugin()
        err = _completed_proc(stdout="", returncode=1, stderr="relation does not exist")
        with patch("subprocess.run", return_value=err):
            result = asyncio.run(plugin._check_pipeline_orphaned(_make_ctx()))
        assert result.status == "warning"
        assert result.needs_healing is False

    def test_qualified_table(self):
        plugin = _make_plugin()
        with patch("subprocess.run", return_value=_completed_proc()) as mock_run:
            asyncio.run(plugin._check_pipeline_orphaned(_make_ctx()))
        sql = mock_run.call_args.args[0][-1]
        assert "sowknow.pipeline_stages" in sql


class TestSentinelQueues:
    def test_watches_real_pipeline_queues(self):
        """The queue-drain check must watch queues that actually exist."""
        plugin = SentinelPlugin(config={})
        mock_result = _completed_proc("0\n")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            asyncio.run(plugin._check_queue_drain(_make_ctx()))
        watched = set()
        for call in mock_run.call_args_list:
            cmd = call.args[0]
            if "LLEN" in cmd:
                watched.add(cmd[cmd.index("LLEN") + 1])
        assert watched == {
            "pipeline.ocr", "pipeline.chunk", "pipeline.embed",
            "pipeline.index", "pipeline.articles", "pipeline.entities",
        }
