"""Analysis Engine — FR4.1 deterministic analysis over extracted facts.

Compute first, narrate second: every output data point is produced by
stdlib statistics (no LLM) and carries the source_refs of the input facts
it derives from (FR4.1.3). When the data cannot support an analysis the
engine says so (FR4.1.4) instead of guessing.

Phase 1 implemented ``descriptive`` and ``trend``. Phase 2 adds
``anomaly`` (z-score / IQR fences, FR4.1.2), ``comparison`` (ranked
totals/means per unit family with pairwise differences) and
``correlation`` (Pearson r over date-aligned pairs, reported only when
statistically meaningful and always labelled "association, not
causation", FR4.1.5) — all deterministic stdlib math through the same
dispatch registry. Unknown analysis types still get an explicit stub.
"""

import logging
import math
import statistics
from typing import Any, Callable

logger = logging.getLogger(__name__)

ANALYSIS_CODE_VERSION = "1.1.0"

# FR4.1.5 threshold defaults; overridable per run() call.
DEFAULT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "trend": {
        "min_time_points": 5,
        "min_periods": 3,
        "moving_average_window": 3,
    },
    "descriptive": {},
    "anomaly": {
        "min_observations_anomaly": 10,
        "z_threshold": 3.0,
        "iqr_factor": 1.5,
    },
    "comparison": {},
    "correlation": {
        "min_pairs_correlation": 30,
        "r_threshold": 0.5,
        "p_threshold": 0.05,
    },
}

INSUFFICIENT_TREND_MESSAGE = "no significant trend detected"
INSUFFICIENT_ANOMALY_MESSAGE = "no significant anomaly detected"
NO_COMPARABLE_MESSAGE = "no comparable metrics found"
NO_CORRELATION_MESSAGE = "no significant correlation"
NOT_ENABLED_MESSAGE = "analysis not enabled in this phase"

# FR4.1.5 — mandatory label on every reported correlation.
CORRELATION_LABEL = "association, not causation"


def _refs(fact: dict) -> list[dict]:
    ref = fact.get("source_ref")
    return [ref] if ref else []


def _period_sort_key(period: str) -> tuple:
    """Sortable key for ISO dates / bare years / unknown periods."""
    digits = "".join(c for c in str(period) if c.isdigit())
    return (0, int(digits.ljust(8, "0") or 0)) if digits else (1, 0)


def _year_of(period: str | None) -> int | None:
    if not period:
        return None
    digits = "".join(c for c in str(period)[:10] if c.isdigit())
    if len(digits) >= 4:
        year = int(digits[:4])
        if 1900 <= year <= 2100:
            return year
    return None


class AnalysisEngine:
    """FR4.1 deterministic analyses. No LLM, no DB — pure functions."""

    ANALYSIS_CODE_VERSION = ANALYSIS_CODE_VERSION

    def __init__(self) -> None:
        # Dispatch registry: every implemented analysis type registers here.
        self._dispatch: dict[str, Callable] = {
            "descriptive": self._descriptive,
            "trend": self._trend,
            "anomaly": self._anomaly,
            "comparison": self._comparison,
            "correlation": self._correlation,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        facts: list[dict],
        analysis_types: list[str],
        thresholds: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict]:
        """Run the requested analyses over the (validated) facts.

        Returns one result dict per analysis type:
        {analysis_type, inputs, output, thresholds_used, provenance,
         code_version}.
        """
        merged = {k: dict(v) for k, v in DEFAULT_THRESHOLDS.items()}
        for key, override in (thresholds or {}).items():
            merged.setdefault(key, {}).update(override)

        numeric_facts = [
            f for f in facts if isinstance(f.get("value"), (int, float))
        ]

        results = []
        for analysis_type in analysis_types:
            handler = self._dispatch.get(analysis_type)
            if handler is None:
                results.append(self._phase_stub(analysis_type))
                continue
            results.append(
                handler(numeric_facts, merged.get(analysis_type, {}))
            )
        return results

    # ------------------------------------------------------------------
    # Result envelope helpers
    # ------------------------------------------------------------------

    def _envelope(
        self,
        analysis_type: str,
        facts: list[dict],
        output: dict,
        thresholds_used: dict,
    ) -> dict:
        provenance = [ref for f in facts for ref in _refs(f)]
        return {
            "analysis_type": analysis_type,
            "inputs": {
                "fact_count": len(facts),
                "metrics": sorted({f.get("name") for f in facts if f.get("name")}),
            },
            "output": output,
            "thresholds_used": thresholds_used,
            "provenance": provenance,
            "code_version": self.ANALYSIS_CODE_VERSION,
        }

    def _phase_stub(self, analysis_type: str) -> dict:
        """Unknown analysis types: explicit stub, never silent."""
        logger.warning("Unknown analysis type %r — returning stub", analysis_type)
        return {
            "analysis_type": analysis_type,
            "inputs": {"fact_count": 0, "metrics": []},
            "output": {
                "sufficient_data": False,
                "message": NOT_ENABLED_MESSAGE,
            },
            "thresholds_used": {},
            "provenance": [],
            "code_version": self.ANALYSIS_CODE_VERSION,
        }

    # ------------------------------------------------------------------
    # descriptive
    # ------------------------------------------------------------------

    def _descriptive(self, facts: list[dict], thresholds: dict) -> dict:
        by_metric: dict[tuple[str, str | None], list[dict]] = {}
        for f in facts:
            by_metric.setdefault((f.get("name"), f.get("unit")), []).append(f)

        metrics = []
        for (name, unit), group in sorted(
            by_metric.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")
        ):
            values = [f["value"] for f in group]
            distribution: dict[str, dict] = {}
            for f in group:
                period = f.get("date") or "unknown"
                bucket = distribution.setdefault(
                    period, {"count": 0, "total": 0.0}
                )
                bucket["count"] += 1
                bucket["total"] += f["value"]
            for bucket in distribution.values():
                bucket["mean"] = bucket["total"] / bucket["count"]
            metrics.append(
                {
                    "metric": name,
                    "unit": unit,
                    "count": len(values),
                    "total": sum(values),
                    "mean": statistics.fmean(values),
                    "min": min(values),
                    "max": max(values),
                    "distribution_by_period": distribution,
                    # FR4.1.3 — every data point keeps its source refs.
                    "values": [
                        {
                            "value": f["value"],
                            "date": f.get("date"),
                            "source_refs": _refs(f),
                        }
                        for f in group
                    ],
                }
            )
        return self._envelope(
            "descriptive", facts, {"metrics": metrics}, thresholds
        )

    # ------------------------------------------------------------------
    # trend
    # ------------------------------------------------------------------

    def _trend(self, facts: list[dict], thresholds: dict) -> dict:
        min_points = thresholds["min_time_points"]
        min_periods = thresholds["min_periods"]
        window = thresholds["moving_average_window"]

        by_metric: dict[tuple[str, str | None], list[dict]] = {}
        for f in facts:
            if f.get("date"):
                by_metric.setdefault((f.get("name"), f.get("unit")), []).append(f)

        trends = []
        for (name, unit), group in sorted(
            by_metric.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")
        ):
            points = sorted(group, key=lambda f: _period_sort_key(f["date"]))
            periods = {f["date"] for f in points}
            if len(points) < min_points or len(periods) < min_periods:
                # FR4.1.4 — never guess a trend from thin data.
                trends.append(
                    {
                        "metric": name,
                        "unit": unit,
                        "sufficient_data": False,
                        "message": INSUFFICIENT_TREND_MESSAGE,
                        "time_points": len(points),
                        "periods": len(periods),
                    }
                )
                continue

            values = [f["value"] for f in points]
            slope, intercept = self._least_squares(values)
            moving_average = [
                statistics.fmean(values[max(0, i - window + 1): i + 1])
                for i in range(len(values))
            ]
            trends.append(
                {
                    "metric": name,
                    "unit": unit,
                    "sufficient_data": True,
                    "slope": slope,
                    "intercept": intercept,
                    "direction": (
                        "increasing" if slope > 0
                        else "decreasing" if slope < 0
                        else "stable"
                    ),
                    "moving_average": moving_average,
                    "moving_average_window": window,
                    "yoy_changes": self._yoy_changes(points),
                    "points": [
                        {
                            "period": f["date"],
                            "value": f["value"],
                            "source_refs": _refs(f),
                        }
                        for f in points
                    ],
                }
            )

        return self._envelope("trend", facts, {"trends": trends}, thresholds)

    @staticmethod
    def _least_squares(values: list[float]) -> tuple[float, float]:
        """Simple linear regression over the sequence index (stdlib)."""
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = statistics.fmean(values)
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator else 0.0
        return slope, y_mean - slope * x_mean

    @staticmethod
    def _yoy_changes(points: list[dict]) -> list[dict]:
        """Year-over-year changes when points span >=2 distinct years."""
        by_year: dict[int, list[dict]] = {}
        for f in points:
            year = _year_of(f.get("date"))
            if year is not None:
                by_year.setdefault(year, []).append(f)
        changes = []
        years = sorted(by_year)
        for prev, cur in zip(years, years[1:]):
            prev_val = statistics.fmean(f["value"] for f in by_year[prev])
            cur_val = statistics.fmean(f["value"] for f in by_year[cur])
            change_pct = (
                (cur_val - prev_val) / abs(prev_val) * 100
                if prev_val != 0
                else None
            )
            changes.append(
                {
                    "from_year": prev,
                    "to_year": cur,
                    "from_value": prev_val,
                    "to_value": cur_val,
                    "change_pct": change_pct,
                    "source_refs": [
                        ref
                        for f in by_year[prev] + by_year[cur]
                        for ref in _refs(f)
                    ],
                }
            )
        return changes

    # ------------------------------------------------------------------
    # anomaly (FR4.1.2)
    # ------------------------------------------------------------------

    def _anomaly(self, facts: list[dict], thresholds: dict) -> dict:
        """Flag outliers per metric: |z| > z_threshold OR outside the
        IQR×iqr_factor fences (either rule fires; both are recorded)."""
        min_obs = thresholds["min_observations_anomaly"]
        z_threshold = thresholds["z_threshold"]
        iqr_factor = thresholds["iqr_factor"]

        by_metric: dict[tuple[str, str | None], list[dict]] = {}
        for f in facts:
            by_metric.setdefault((f.get("name"), f.get("unit")), []).append(f)

        metrics = []
        for (name, unit), group in sorted(
            by_metric.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")
        ):
            points = sorted(group, key=lambda f: _period_sort_key(f.get("date") or ""))
            if len(points) < min_obs:
                # FR4.1.4 — thin data gets an honest answer, not a guess.
                metrics.append(
                    {
                        "metric": name,
                        "unit": unit,
                        "sufficient_data": False,
                        "message": INSUFFICIENT_ANOMALY_MESSAGE,
                        "observation_count": len(points),
                    }
                )
                continue

            values = [f["value"] for f in points]
            mean = statistics.fmean(values)
            stdev = statistics.pstdev(values)
            q1, _q2, q3 = statistics.quantiles(values, n=4)
            iqr = q3 - q1
            fence_lower = q1 - iqr_factor * iqr
            fence_upper = q3 + iqr_factor * iqr

            anomalies = []
            for f in points:
                value = f["value"]
                z_score = (value - mean) / stdev if stdev > 0 else 0.0
                rules = []
                if stdev > 0 and abs(z_score) > z_threshold:
                    rules.append("z_score")
                if value < fence_lower or value > fence_upper:
                    rules.append("iqr_fence")
                if not rules:
                    continue
                anomalies.append(
                    {
                        "value": value,
                        "date": f.get("date"),
                        "rules": rules,
                        "z_score": round(z_score, 4),
                        "fence_lower": fence_lower,
                        "fence_upper": fence_upper,
                        "source_refs": _refs(f),
                    }
                )
            metrics.append(
                {
                    "metric": name,
                    "unit": unit,
                    "sufficient_data": True,
                    "observation_count": len(points),
                    "mean": mean,
                    "stdev": stdev,
                    "anomalies": anomalies,
                }
            )
        return self._envelope("anomaly", facts, {"metrics": metrics}, thresholds)

    # ------------------------------------------------------------------
    # comparison
    # ------------------------------------------------------------------

    @staticmethod
    def _comparison_family(fact: dict) -> tuple[tuple, str, str]:
        """Map a fact to (family_key, label, dimension).

        - a ``group`` key on the fact wins: compare groups within the
          same metric name + unit;
        - a ``name: label`` separator splits into family/label;
        - otherwise metrics are compared within their unit family.
        """
        name = str(fact.get("name") or "value")
        unit = fact.get("unit")
        if fact.get("group") is not None:
            return (name, unit), str(fact["group"]), "group"
        if ":" in name:
            prefix, suffix = name.split(":", 1)
            prefix, suffix = prefix.strip(), suffix.strip()
            if prefix and suffix:
                return (prefix, unit), suffix, "group"
        return (unit,), name, "metric"

    def _comparison(self, facts: list[dict], thresholds: dict) -> dict:
        """Rank labels within each comparable family and compute pairwise
        differences (totals and means), all with source refs."""
        families: dict[tuple, dict[str, Any]] = {}
        for f in facts:
            family_key, label, dimension = self._comparison_family(f)
            family = families.setdefault(
                family_key, {"dimension": dimension, "by_label": {}}
            )
            family["by_label"].setdefault(label, []).append(f)

        comparisons = []
        for (family_key, family) in sorted(
            families.items(), key=lambda kv: (str(kv[0]), kv[1]["dimension"])
        ):
            by_label = family["by_label"]
            if len(by_label) < 2:
                continue  # nothing to compare within this family
            unit = family_key[0] if len(family_key) == 1 else family_key[1]
            family_name = None if len(family_key) == 1 else family_key[0]

            aggregates = []
            for label, group in sorted(by_label.items()):
                values = [f["value"] for f in group]
                aggregates.append(
                    {
                        "label": label,
                        "count": len(values),
                        "total": sum(values),
                        "mean": statistics.fmean(values),
                        "source_refs": [ref for f in group for ref in _refs(f)],
                    }
                )
            ranking = sorted(aggregates, key=lambda a: (-a["total"], a["label"]))
            for position, entry in enumerate(ranking, start=1):
                entry["rank"] = position

            pairwise = []
            for i, a in enumerate(ranking):
                for b in ranking[i + 1:]:
                    pairwise.append(
                        {
                            "a": a["label"],
                            "b": b["label"],
                            "total_difference": a["total"] - b["total"],
                            "mean_difference": a["mean"] - b["mean"],
                            "source_refs": a["source_refs"] + b["source_refs"],
                        }
                    )
            comparisons.append(
                {
                    "family": family_name,
                    "dimension": family["dimension"],
                    "unit": unit,
                    "ranking": ranking,
                    "pairwise": pairwise,
                }
            )

        if not comparisons:
            return self._envelope(
                "comparison",
                facts,
                {"sufficient_data": False, "message": NO_COMPARABLE_MESSAGE},
                thresholds,
            )
        return self._envelope(
            "comparison",
            facts,
            {"sufficient_data": True, "comparisons": comparisons},
            thresholds,
        )

    # ------------------------------------------------------------------
    # correlation (FR4.1.5)
    # ------------------------------------------------------------------

    @staticmethod
    def _pearson(xs: list[float], ys: list[float]) -> float | None:
        """Stdlib Pearson r; None when a series has zero variance."""
        n = len(xs)
        if n < 2:
            return None
        x_mean = statistics.fmean(xs)
        y_mean = statistics.fmean(ys)
        sxx = sum((x - x_mean) ** 2 for x in xs)
        syy = sum((y - y_mean) ** 2 for y in ys)
        if sxx == 0 or syy == 0:
            return None
        sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        return sxy / math.sqrt(sxx * syy)

    @staticmethod
    def _correlation_p_value(r: float, n: int) -> float:
        """Two-tailed p-value for H0: r == 0.

        t = r·sqrt((n−2)/(1−r²)) is Student-distributed with n−2 df; for
        n >= 30 (enforced by min_pairs_correlation) the normal
        approximation p = 2·(1 − Φ(|t|)) = erfc(|t|/√2) is accurate to
        ~1e-3 and needs no scipy.
        """
        if n <= 2:
            return 1.0
        r = max(-0.999999, min(0.999999, r))  # keep 1−r² positive
        t = abs(r) * math.sqrt((n - 2) / (1 - r * r))
        return math.erfc(t / math.sqrt(2))

    def _correlation(self, facts: list[dict], thresholds: dict) -> dict:
        """Pair metrics that share periods (aligned by date); report pairs
        with |r| >= r_threshold AND p < p_threshold only."""
        min_pairs = thresholds["min_pairs_correlation"]
        r_threshold = thresholds["r_threshold"]
        p_threshold = thresholds["p_threshold"]

        # (name, unit) -> {date: mean of values on that date} + refs
        series: dict[tuple[str, str | None], dict[str, Any]] = {}
        for f in facts:
            if not f.get("date"):
                continue
            key = (f.get("name"), f.get("unit"))
            entry = series.setdefault(key, {"by_date": {}, "refs": {}})
            date = str(f["date"])
            entry["by_date"].setdefault(date, []).append(f["value"])
            entry["refs"].setdefault(date, []).extend(_refs(f))
        for entry in series.values():
            entry["by_date"] = {
                d: statistics.fmean(v) for d, v in entry["by_date"].items()
            }

        keys = sorted(series, key=lambda k: (k[0] or "", k[1] or ""))
        reported = []
        best: dict[str, Any] | None = None
        for i, key_a in enumerate(keys):
            for key_b in keys[i + 1:]:
                shared = sorted(
                    set(series[key_a]["by_date"]) & set(series[key_b]["by_date"]),
                    key=_period_sort_key,
                )
                if len(shared) < min_pairs:
                    continue
                xs = [series[key_a]["by_date"][d] for d in shared]
                ys = [series[key_b]["by_date"][d] for d in shared]
                r = self._pearson(xs, ys)
                if r is None:
                    continue
                refs = [
                    ref
                    for d in shared
                    for ref in series[key_a]["refs"].get(d, [])
                    + series[key_b]["refs"].get(d, [])
                ]
                p_value = self._correlation_p_value(r, len(shared))
                candidate = {
                    "metric_a": key_a[0],
                    "metric_b": key_b[0],
                    "n": len(shared),
                    "r": round(r, 4),
                    "source_refs": refs,
                }
                if best is None or abs(r) > abs(best["r"]):
                    best = candidate
                if abs(r) >= r_threshold and p_value < p_threshold:
                    reported.append(
                        {
                            **candidate,
                            "p_value": p_value,
                            # FR4.1.5 — mandatory caveat on every report.
                            "label": CORRELATION_LABEL,
                        }
                    )

        if not reported:
            output: dict[str, Any] = {
                "sufficient_data": False,
                "message": NO_CORRELATION_MESSAGE,
                # Transparency: the strongest association observed, even
                # when below the reporting bar.
                "best_observed": best,
            }
            return self._envelope("correlation", facts, output, thresholds)
        return self._envelope(
            "correlation",
            facts,
            {"sufficient_data": True, "correlations": reported},
            thresholds,
        )
