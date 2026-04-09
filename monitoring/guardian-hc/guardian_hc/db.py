from __future__ import annotations

import json
import math
import datetime
from typing import Any

try:
    import asyncpg  # type: ignore
except ImportError:
    asyncpg = None  # type: ignore

import aiosqlite


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS guardian_metrics (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    metric  TEXT NOT NULL,
    service TEXT NOT NULL DEFAULT '',
    value   REAL NOT NULL,
    tags    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS guardian_patterns (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_name       TEXT NOT NULL,
    trigger_conditions TEXT NOT NULL DEFAULT '{}',
    predicted_outcome  TEXT NOT NULL DEFAULT '',
    recommended_action TEXT NOT NULL DEFAULT '',
    confidence         REAL NOT NULL DEFAULT 0.5,
    times_matched      INTEGER NOT NULL DEFAULT 0,
    times_correct      INTEGER NOT NULL DEFAULT 0,
    last_matched       TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    active             INTEGER NOT NULL DEFAULT 1
);
"""

_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS guardian_metrics (
    id      BIGSERIAL PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metric  VARCHAR(255) NOT NULL,
    service VARCHAR(255) NOT NULL DEFAULT '',
    value   DOUBLE PRECISION NOT NULL,
    tags    JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS guardian_patterns (
    id                 BIGSERIAL PRIMARY KEY,
    pattern_name       VARCHAR(255) NOT NULL,
    trigger_conditions JSONB NOT NULL DEFAULT '{}',
    predicted_outcome  TEXT NOT NULL DEFAULT '',
    recommended_action TEXT NOT NULL DEFAULT '',
    confidence         DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    times_matched      INTEGER NOT NULL DEFAULT 0,
    times_correct      INTEGER NOT NULL DEFAULT 0,
    last_matched       TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active             BOOLEAN NOT NULL DEFAULT TRUE
);
"""


def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()


class MetricsDB:
    """Shared database layer for Guardian v2 metrics and patterns.

    Connects to PostgreSQL when pg_dsn is provided; falls back to SQLite
    (aiosqlite) for resilience when PostgreSQL is unavailable.
    """

    def __init__(self, pg_dsn: str | None, fallback_path: str = "/tmp/guardian-metrics-buffer.db") -> None:
        self._pg_dsn = pg_dsn
        self._fallback_path = fallback_path
        self._pg_conn: Any = None          # asyncpg connection
        self._sqlite_conn: Any = None      # aiosqlite connection
        self._use_pg = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to PostgreSQL if configured, else fall back to SQLite."""
        if self._pg_dsn and asyncpg is not None:
            try:
                self._pg_conn = await asyncpg.connect(self._pg_dsn)
                await self._pg_conn.execute(_PG_SCHEMA)
                self._use_pg = True
                return
            except Exception:
                pass  # Fall through to SQLite

        # SQLite fallback
        self._sqlite_conn = await aiosqlite.connect(self._fallback_path)
        self._sqlite_conn.row_factory = aiosqlite.Row
        await self._sqlite_conn.executescript(_SQLITE_SCHEMA)
        await self._sqlite_conn.commit()
        self._use_pg = False

    async def close(self) -> None:
        """Close active database connection."""
        if self._pg_conn is not None:
            await self._pg_conn.close()
            self._pg_conn = None
        if self._sqlite_conn is not None:
            await self._sqlite_conn.close()
            self._sqlite_conn = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_pg(self) -> bool:
        """True if connected to PostgreSQL, False if using SQLite."""
        return self._use_pg

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cutoff_iso(self, hours: int) -> str:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        return cutoff.isoformat()

    # ------------------------------------------------------------------
    # Metric writes
    # ------------------------------------------------------------------

    async def write_metric(
        self,
        metric: str,
        value: float,
        service: str = "",
        tags: dict | None = None,
    ) -> None:
        """Insert a single metric row."""
        if tags is None:
            tags = {}
        if self._use_pg and self._pg_conn is not None:
            await self._pg_conn.execute(
                "INSERT INTO guardian_metrics (metric, value, service, tags) VALUES ($1, $2, $3, $4)",
                metric,
                value,
                service,
                json.dumps(tags),
            )
        else:
            ts = _now_iso()
            await self._sqlite_conn.execute(
                "INSERT INTO guardian_metrics (ts, metric, service, value, tags) VALUES (?, ?, ?, ?, ?)",
                (ts, metric, service, value, json.dumps(tags)),
            )
            await self._sqlite_conn.commit()

    async def write_batch(self, metrics: list[tuple[str, float, str, dict]]) -> None:
        """Insert multiple metrics at once.

        Each tuple: (metric, value, service, tags).
        """
        if self._use_pg and self._pg_conn is not None:
            rows = [(m, v, s, json.dumps(t)) for m, v, s, t in metrics]
            await self._pg_conn.executemany(
                "INSERT INTO guardian_metrics (metric, value, service, tags) VALUES ($1, $2, $3, $4)",
                rows,
            )
        else:
            ts = _now_iso()
            rows = [(ts, m, s, v, json.dumps(t)) for m, v, s, t in metrics]
            await self._sqlite_conn.executemany(
                "INSERT INTO guardian_metrics (ts, metric, service, value, tags) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            await self._sqlite_conn.commit()

    # ------------------------------------------------------------------
    # Metric reads
    # ------------------------------------------------------------------

    async def query_metrics(
        self,
        metric: str,
        hours: int = 24,
        service: str | None = None,
    ) -> list[dict]:
        """Return metrics within `hours` time window, newest first."""
        cutoff = self._cutoff_iso(hours)

        if self._use_pg and self._pg_conn is not None:
            if service is not None:
                rows = await self._pg_conn.fetch(
                    "SELECT * FROM guardian_metrics WHERE metric=$1 AND ts > $2 AND service=$3 ORDER BY ts DESC",
                    metric, cutoff, service,
                )
            else:
                rows = await self._pg_conn.fetch(
                    "SELECT * FROM guardian_metrics WHERE metric=$1 AND ts > $2 ORDER BY ts DESC",
                    metric, cutoff,
                )
            return [dict(r) for r in rows]
        else:
            if service is not None:
                async with self._sqlite_conn.execute(
                    "SELECT * FROM guardian_metrics WHERE metric=? AND ts > ? AND service=? ORDER BY ts DESC",
                    (metric, cutoff, service),
                ) as cursor:
                    rows = await cursor.fetchall()
            else:
                async with self._sqlite_conn.execute(
                    "SELECT * FROM guardian_metrics WHERE metric=? AND ts > ? ORDER BY ts DESC",
                    (metric, cutoff),
                ) as cursor:
                    rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_latest(self, metric: str, service: str | None = None) -> float | None:
        """Return the most recently inserted value for a metric."""
        if self._use_pg and self._pg_conn is not None:
            if service is not None:
                row = await self._pg_conn.fetchrow(
                    "SELECT value FROM guardian_metrics WHERE metric=$1 AND service=$2 ORDER BY ts DESC LIMIT 1",
                    metric, service,
                )
            else:
                row = await self._pg_conn.fetchrow(
                    "SELECT value FROM guardian_metrics WHERE metric=$1 ORDER BY ts DESC LIMIT 1",
                    metric,
                )
            return float(row["value"]) if row else None
        else:
            if service is not None:
                async with self._sqlite_conn.execute(
                    "SELECT value FROM guardian_metrics WHERE metric=? AND service=? ORDER BY ts DESC LIMIT 1",
                    (metric, service),
                ) as cursor:
                    row = await cursor.fetchone()
            else:
                async with self._sqlite_conn.execute(
                    "SELECT value FROM guardian_metrics WHERE metric=? ORDER BY ts DESC LIMIT 1",
                    (metric,),
                ) as cursor:
                    row = await cursor.fetchone()
            return float(row["value"]) if row else None

    async def get_slope(
        self,
        metric: str,
        hours: int = 6,
        service: str | None = None,
    ) -> float | None:
        """Linear regression slope (value-per-hour) over the time window.

        Returns None when fewer than 2 data points exist.
        The x-axis is hours_ago (positive = older), so slope is negated
        to express value change per hour going forward.
        """
        rows = await self.query_metrics(metric, hours=hours, service=service)
        if len(rows) < 2:
            return None

        now = datetime.datetime.utcnow()
        xs: list[float] = []
        ys: list[float] = []
        for row in rows:
            ts_str = row["ts"]
            # Normalise ISO string (strip trailing Z if present)
            if isinstance(ts_str, str):
                ts_str = ts_str.rstrip("Z")
                ts = datetime.datetime.fromisoformat(ts_str)
            else:
                ts = ts_str  # datetime object (PG)
            hours_ago = (now - ts).total_seconds() / 3600.0
            xs.append(hours_ago)
            ys.append(float(row["value"]))

        n = len(xs)
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        denominator = sum((x - x_mean) ** 2 for x in xs)

        if denominator == 0.0:
            return None

        # Negate: hours_ago decreases as metrics are newer, so raw slope
        # is negative for increasing values — invert to get forward slope.
        return -(numerator / denominator)

    async def get_mean_stddev(
        self,
        metric: str,
        hours: int = 24,
        service: str | None = None,
    ) -> tuple[float, float]:
        """Return (mean, sample stddev) for metric values in the window.

        Returns (0.0, 0.0) when no data exists.
        Returns (mean, 0.0) for a single data point.
        """
        rows = await self.query_metrics(metric, hours=hours, service=service)
        if not rows:
            return (0.0, 0.0)

        values = [float(r["value"]) for r in rows]
        n = len(values)
        mean = sum(values) / n

        if n == 1:
            return (mean, 0.0)

        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        return (mean, math.sqrt(variance))

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def purge_raw_metrics(self, hours: int = 48) -> int:
        """Delete metrics older than `hours`. Returns count deleted."""
        cutoff = self._cutoff_iso(hours)

        if self._use_pg and self._pg_conn is not None:
            result = await self._pg_conn.execute(
                "DELETE FROM guardian_metrics WHERE ts < $1", cutoff
            )
            # asyncpg returns "DELETE N"
            return int(result.split()[-1])
        else:
            async with self._sqlite_conn.execute(
                "DELETE FROM guardian_metrics WHERE ts < ?", (cutoff,)
            ) as cursor:
                count = cursor.rowcount
            await self._sqlite_conn.commit()
            return count if count is not None else 0

    # ------------------------------------------------------------------
    # Pattern management
    # ------------------------------------------------------------------

    async def create_pattern(
        self,
        pattern_name: str,
        trigger_conditions: dict,
        predicted_outcome: str,
        recommended_action: str,
        confidence: float = 0.5,
    ) -> int:
        """Insert a new pattern and return its id."""
        tc_json = json.dumps(trigger_conditions)

        if self._use_pg and self._pg_conn is not None:
            row = await self._pg_conn.fetchrow(
                """INSERT INTO guardian_patterns
                   (pattern_name, trigger_conditions, predicted_outcome, recommended_action, confidence)
                   VALUES ($1, $2, $3, $4, $5) RETURNING id""",
                pattern_name, tc_json, predicted_outcome, recommended_action, confidence,
            )
            return int(row["id"])
        else:
            async with self._sqlite_conn.execute(
                """INSERT INTO guardian_patterns
                   (pattern_name, trigger_conditions, predicted_outcome, recommended_action, confidence)
                   VALUES (?, ?, ?, ?, ?)""",
                (pattern_name, tc_json, predicted_outcome, recommended_action, confidence),
            ) as cursor:
                pattern_id = cursor.lastrowid
            await self._sqlite_conn.commit()
            return pattern_id  # type: ignore[return-value]

    async def get_active_patterns(self) -> list[dict]:
        """Return all active patterns ordered by confidence DESC."""
        if self._use_pg and self._pg_conn is not None:
            rows = await self._pg_conn.fetch(
                "SELECT * FROM guardian_patterns WHERE active=TRUE ORDER BY confidence DESC"
            )
            return [dict(r) for r in rows]
        else:
            async with self._sqlite_conn.execute(
                "SELECT * FROM guardian_patterns WHERE active=1 ORDER BY confidence DESC"
            ) as cursor:
                rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                # Parse trigger_conditions from JSON string
                if isinstance(d.get("trigger_conditions"), str):
                    try:
                        d["trigger_conditions"] = json.loads(d["trigger_conditions"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                result.append(d)
            return result

    async def update_pattern_confidence(
        self, pattern_id: int, matched: bool, correct: bool
    ) -> None:
        """Adjust confidence based on outcome.

        - correct=True: +0.1, capped at 0.95
        - correct=False: -0.05, floored at 0.1
        - Deactivate if confidence < 0.2
        """
        # Fetch current confidence
        if self._use_pg and self._pg_conn is not None:
            row = await self._pg_conn.fetchrow(
                "SELECT confidence FROM guardian_patterns WHERE id=$1", pattern_id
            )
            current = float(row["confidence"]) if row else 0.5
        else:
            async with self._sqlite_conn.execute(
                "SELECT confidence FROM guardian_patterns WHERE id=?", (pattern_id,)
            ) as cursor:
                row = await cursor.fetchone()
            current = float(row["confidence"]) if row else 0.5

        if correct:
            new_conf = min(0.95, current + 0.1)
        else:
            new_conf = max(0.1, current - 0.05)

        now_ts = _now_iso()
        active = 0 if new_conf < 0.2 else 1

        if self._use_pg and self._pg_conn is not None:
            pg_active = active == 1
            await self._pg_conn.execute(
                """UPDATE guardian_patterns
                   SET confidence=$1, times_matched=times_matched+1,
                       times_correct=times_correct + $2,
                       last_matched=$3, active=$4
                   WHERE id=$5""",
                new_conf,
                1 if correct else 0,
                now_ts,
                pg_active,
                pattern_id,
            )
        else:
            await self._sqlite_conn.execute(
                """UPDATE guardian_patterns
                   SET confidence=?, times_matched=times_matched+1,
                       times_correct=times_correct + ?,
                       last_matched=?, active=?
                   WHERE id=?""",
                (new_conf, 1 if correct else 0, now_ts, active, pattern_id),
            )
            await self._sqlite_conn.commit()
