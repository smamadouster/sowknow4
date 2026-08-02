"""FR4.1 analysis engine tests — descriptive stats, trend thresholds,
Phase-2 stubs, threshold overrides."""

import pytest

from app.services.collection_orchestrator.analysis_engine import (
    ANALYSIS_CODE_VERSION,
    AnalysisEngine,
)


@pytest.fixture
def engine():
    return AnalysisEngine()


def _fact(name, value, date=None, unit=None, doc="d1", page=1):
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "date": date,
        "source_ref": {"document_id": doc, "chunk_id": "c1", "page": page},
        "confidence": 0.9,
        "origin": "table",
    }


class TestDescriptive:
    def test_stats_correctness(self, engine):
        facts = [
            _fact("revenue", 10.0, "2023"),
            _fact("revenue", 20.0, "2023"),
            _fact("revenue", 30.0, "2024"),
        ]
        [result] = engine.run(facts, ["descriptive"])
        assert result["analysis_type"] == "descriptive"
        assert result["code_version"] == ANALYSIS_CODE_VERSION
        [metric] = result["output"]["metrics"]
        assert metric["metric"] == "revenue"
        assert metric["count"] == 3
        assert metric["total"] == 60.0
        assert metric["mean"] == pytest.approx(20.0)
        assert metric["min"] == 10.0
        assert metric["max"] == 30.0

    def test_distribution_by_period(self, engine):
        facts = [
            _fact("revenue", 10.0, "2023"),
            _fact("revenue", 30.0, "2024"),
        ]
        [result] = engine.run(facts, ["descriptive"])
        dist = result["output"]["metrics"][0]["distribution_by_period"]
        assert dist["2023"]["count"] == 1
        assert dist["2024"]["mean"] == 30.0

    def test_values_carry_source_refs(self, engine):
        facts = [_fact("revenue", 10.0, "2023", doc="dX", page=7)]
        [result] = engine.run(facts, ["descriptive"])
        value = result["output"]["metrics"][0]["values"][0]
        assert value["source_refs"] == [
            {"document_id": "dX", "chunk_id": "c1", "page": 7}
        ]
        assert result["provenance"] == value["source_refs"]

    def test_date_facts_ignored(self, engine):
        facts = [{"name": "date", "value": None, "date": "2024",
                  "source_ref": None}]
        [result] = engine.run(facts, ["descriptive"])
        assert result["output"]["metrics"] == []


class TestTrend:
    def _series(self, values, start_year=2020):
        return [
            _fact("revenue", v, str(start_year + i))
            for i, v in enumerate(values)
        ]

    def test_four_points_insufficient(self, engine):
        facts = self._series([100.0, 110.0, 120.0, 130.0])  # 4 points/4 periods
        [result] = engine.run(facts, ["trend"])
        [trend] = result["output"]["trends"]
        assert trend["sufficient_data"] is False
        assert trend["message"] == "no significant trend detected"

    def test_fewer_than_three_periods_insufficient(self, engine):
        # 6 points but only 2 distinct period values
        facts = [
            _fact("revenue", 100.0, "2023", doc="d1"),
            _fact("revenue", 101.0, "2023", doc="d2"),
            _fact("revenue", 102.0, "2023", doc="d3"),
            _fact("revenue", 103.0, "2024", doc="d4"),
            _fact("revenue", 104.0, "2024", doc="d5"),
            _fact("revenue", 105.0, "2024", doc="d6"),
        ]
        [result] = engine.run(facts, ["trend"])
        [trend] = result["output"]["trends"]
        assert trend["sufficient_data"] is False

    def test_six_points_four_periods_full_output(self, engine):
        # 6 points across 4 periods (2021 has extra H1/H2 points)
        facts = [
            _fact("revenue", 100.0, "2021-06-30", doc="d1"),
            _fact("revenue", 110.0, "2021-12-31", doc="d2"),
            _fact("revenue", 120.0, "2022-12-31", doc="d3"),
            _fact("revenue", 130.0, "2023-06-30", doc="d4"),
            _fact("revenue", 140.0, "2023-12-31", doc="d5"),
            _fact("revenue", 150.0, "2024-12-31", doc="d6"),
        ]
        [result] = engine.run(facts, ["trend"])
        [trend] = result["output"]["trends"]
        assert trend["sufficient_data"] is True
        assert trend["slope"] > 0
        assert trend["direction"] == "increasing"
        assert len(trend["moving_average"]) == 6
        assert trend["moving_average_window"] == 3
        # YoY across the 4 distinct years
        years = [(c["from_year"], c["to_year"]) for c in trend["yoy_changes"]]
        assert years == [(2021, 2022), (2022, 2023), (2023, 2024)]
        change = trend["yoy_changes"][0]
        # 2021 mean = 105, 2022 = 120 -> +14.29%
        assert change["change_pct"] == pytest.approx((120 - 105) / 105 * 100)
        assert change["source_refs"]  # FR4.1.3 provenance on every point
        assert all(p["source_refs"] for p in trend["points"])

    def test_thresholds_recorded_and_overridable(self, engine):
        facts = self._series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        [default] = engine.run(facts, ["trend"])
        assert default["thresholds_used"]["min_time_points"] == 5
        assert default["output"]["trends"][0]["sufficient_data"] is True

        [strict] = engine.run(
            facts, ["trend"], thresholds={"trend": {"min_time_points": 10}}
        )
        assert strict["thresholds_used"]["min_time_points"] == 10
        assert strict["output"]["trends"][0]["sufficient_data"] is False


class TestAnomaly:
    def _series(self, values, unit="XOF"):
        return [
            _fact("revenue", v, f"2024-{i + 1:02d}-01", unit=unit)
            for i, v in enumerate(values)
        ]

    def test_nine_observations_insufficient(self, engine):
        facts = self._series([100.0 + i for i in range(9)])
        [result] = engine.run(facts, ["anomaly"])
        [metric] = result["output"]["metrics"]
        assert metric["sufficient_data"] is False
        assert metric["message"] == "no significant anomaly detected"
        assert metric["observation_count"] == 9

    def test_twelve_observations_clear_outlier_flagged(self, engine):
        facts = self._series([100.0 + i for i in range(11)] + [10_000.0])
        [result] = engine.run(facts, ["anomaly"])
        [metric] = result["output"]["metrics"]
        assert metric["sufficient_data"] is True
        assert metric["observation_count"] == 12
        assert len(metric["anomalies"]) == 1
        anomaly = metric["anomalies"][0]
        assert anomaly["value"] == 10_000.0
        assert anomaly["date"] == "2024-12-01"
        assert set(anomaly["rules"]) == {"z_score", "iqr_fence"}
        assert anomaly["z_score"] > 3.0
        assert anomaly["fence_upper"] < 10_000.0
        assert anomaly["source_refs"]  # FR4.1.3 provenance

    def test_mild_outlier_fires_iqr_fence_only(self, engine):
        # Spread-out cluster + moderate outlier: fence breached (upper
        # fence 37), but |z| ≈ 2.91 stays under the z threshold.
        facts = self._series([float(x) for x in range(0, 22, 2)] + [50.0])
        [result] = engine.run(facts, ["anomaly"])
        [metric] = result["output"]["metrics"]
        assert len(metric["anomalies"]) == 1
        anomaly = metric["anomalies"][0]
        assert anomaly["value"] == 50.0
        assert "iqr_fence" in anomaly["rules"]
        assert "z_score" not in anomaly["rules"]

    def test_clean_series_flags_nothing(self, engine):
        facts = self._series([100.0 + (i % 3) for i in range(12)])
        [result] = engine.run(facts, ["anomaly"])
        [metric] = result["output"]["metrics"]
        assert metric["sufficient_data"] is True
        assert metric["anomalies"] == []

    def test_constant_series_no_anomalies(self, engine):
        facts = self._series([42.0] * 12)  # stdev 0 — z-score rule inert
        [result] = engine.run(facts, ["anomaly"])
        [metric] = result["output"]["metrics"]
        assert metric["sufficient_data"] is True
        assert metric["anomalies"] == []

    def test_thresholds_recorded_and_overridable(self, engine):
        facts = self._series([100.0 + i for i in range(9)])
        [default] = engine.run(facts, ["anomaly"])
        assert default["thresholds_used"]["min_observations_anomaly"] == 10
        assert default["thresholds_used"]["z_threshold"] == 3.0
        assert default["thresholds_used"]["iqr_factor"] == 1.5

        [lenient] = engine.run(
            facts, ["anomaly"],
            thresholds={"anomaly": {"min_observations_anomaly": 5}},
        )
        assert lenient["thresholds_used"]["min_observations_anomaly"] == 5
        assert lenient["output"]["metrics"][0]["sufficient_data"] is True


class TestComparison:
    def test_metrics_ranked_by_total_with_pairwise_differences(self, engine):
        facts = [
            _fact("revenue", 100.0, "2024", unit="XOF", doc="d1"),
            _fact("revenue", 200.0, "2024", unit="XOF", doc="d2"),
            _fact("costs", 50.0, "2024", unit="XOF", doc="d3"),
        ]
        [result] = engine.run(facts, ["comparison"])
        output = result["output"]
        assert output["sufficient_data"] is True
        [comparison] = output["comparisons"]
        assert comparison["dimension"] == "metric"
        assert comparison["unit"] == "XOF"
        ranking = comparison["ranking"]
        assert [r["label"] for r in ranking] == ["revenue", "costs"]
        assert ranking[0]["total"] == 300.0
        assert ranking[0]["rank"] == 1
        assert ranking[1]["rank"] == 2
        [pair] = comparison["pairwise"]
        assert pair["a"] == "revenue"
        assert pair["b"] == "costs"
        assert pair["total_difference"] == 250.0
        assert pair["mean_difference"] == pytest.approx(100.0)  # 150 - 50
        assert pair["source_refs"]  # both sides' refs

    def test_group_key_compares_groups_within_metric(self, engine):
        facts = [
            {**_fact("revenue", 100.0, "2024", unit="XOF", doc="d1"), "group": "Bank A"},
            {**_fact("revenue", 250.0, "2024", unit="XOF", doc="d2"), "group": "Bank B"},
        ]
        [result] = engine.run(facts, ["comparison"])
        [comparison] = result["output"]["comparisons"]
        assert comparison["dimension"] == "group"
        assert comparison["family"] == "revenue"
        assert [r["label"] for r in comparison["ranking"]] == ["Bank B", "Bank A"]

    def test_name_separator_splits_family_and_label(self, engine):
        facts = [
            _fact("revenue: bank a", 100.0, "2024", unit="XOF", doc="d1"),
            _fact("revenue: bank b", 300.0, "2024", unit="XOF", doc="d2"),
        ]
        [result] = engine.run(facts, ["comparison"])
        [comparison] = result["output"]["comparisons"]
        assert comparison["dimension"] == "group"
        assert comparison["family"] == "revenue"
        assert comparison["ranking"][0]["label"] == "bank b"

    def test_separate_unit_families_not_mixed(self, engine):
        facts = [
            _fact("revenue", 100.0, "2024", unit="XOF"),
            _fact("costs", 50.0, "2024", unit="XOF"),
            _fact("margin", 12.0, "2024", unit="%"),
            _fact("growth", 5.0, "2024", unit="%"),
        ]
        [result] = engine.run(facts, ["comparison"])
        units = {c["unit"] for c in result["output"]["comparisons"]}
        assert units == {"XOF", "%"}

    def test_nothing_comparable(self, engine):
        facts = [_fact("revenue", 100.0, "2024", unit="XOF")]
        [result] = engine.run(facts, ["comparison"])
        assert result["output"]["sufficient_data"] is False
        assert result["output"]["message"] == "no comparable metrics found"

    def test_thresholds_recorded(self, engine):
        [result] = engine.run([], ["comparison"])
        assert result["thresholds_used"] == {}


class TestCorrelation:
    def _paired(self, xs, ys, start_day=1):
        """Two metric series aligned on distinct dates."""
        facts = []
        for i, (x, y) in enumerate(zip(xs, ys)):
            date = f"2024-01-{start_day + i:02d}" if start_day + i <= 28 else f"2024-02-{start_day + i - 28:02d}"
            facts.append(_fact("revenue", x, date, unit="XOF", doc=f"dx{i}"))
            facts.append(_fact("costs", y, date, unit="XOF", doc=f"dy{i}"))
        return facts

    def test_fewer_than_30_pairs_insufficient(self, engine):
        xs = [float(i) for i in range(20)]
        ys = [2.0 * i + 1 for i in range(20)]
        [result] = engine.run(self._paired(xs, ys), ["correlation"])
        output = result["output"]
        assert output["sufficient_data"] is False
        assert output["message"] == "no significant correlation"
        assert output["best_observed"] is None  # pair never reached min_pairs

    def test_correlated_series_reported_with_label(self, engine):
        xs = [float(i) for i in range(40)]
        ys = [2.0 * i + 5 for i in range(40)]
        [result] = engine.run(self._paired(xs, ys), ["correlation"])
        output = result["output"]
        assert output["sufficient_data"] is True
        [correlation] = output["correlations"]
        assert correlation["r"] == pytest.approx(1.0)
        assert correlation["n"] == 40
        assert correlation["p_value"] < 0.05
        # FR4.1.5 — mandatory caveat
        assert correlation["label"] == "association, not causation"
        assert correlation["source_refs"]

    def test_anticorrelated_series_reported(self, engine):
        xs = [float(i) for i in range(40)]
        ys = [100.0 - 3.0 * i for i in range(40)]
        [result] = engine.run(self._paired(xs, ys), ["correlation"])
        [correlation] = result["output"]["correlations"]
        assert correlation["r"] == pytest.approx(-1.0)
        assert abs(correlation["r"]) >= 0.5

    def test_uncorrelated_reports_best_observed(self, engine):
        xs = [float(i) for i in range(40)]
        ys = [float(i % 2) for i in range(40)]  # r ≈ 0
        [result] = engine.run(self._paired(xs, ys), ["correlation"])
        output = result["output"]
        assert output["sufficient_data"] is False
        assert output["message"] == "no significant correlation"
        best = output["best_observed"]
        assert best is not None
        assert abs(best["r"]) < 0.5
        assert best["n"] == 40

    def test_zero_variance_series_skipped(self, engine):
        xs = [7.0] * 40  # constant — r undefined
        ys = [float(i) for i in range(40)]
        [result] = engine.run(self._paired(xs, ys), ["correlation"])
        assert result["output"]["sufficient_data"] is False
        assert result["output"]["best_observed"] is None

    def test_thresholds_recorded_and_overridable(self, engine):
        xs = [float(i) for i in range(40)]
        ys = [2.0 * i for i in range(40)]
        [default] = engine.run(self._paired(xs, ys), ["correlation"])
        assert default["thresholds_used"]["min_pairs_correlation"] == 30
        assert default["thresholds_used"]["r_threshold"] == 0.5
        assert default["thresholds_used"]["p_threshold"] == 0.05

        [strict] = engine.run(
            self._paired(xs, ys), ["correlation"],
            thresholds={"correlation": {"r_threshold": 1.5}},
        )
        assert strict["output"]["sufficient_data"] is False
        assert strict["output"]["best_observed"]["r"] == pytest.approx(1.0)

    def test_metrics_need_shared_dates(self, engine):
        # Same metric names universe but disjoint dates → no pairing.
        facts = [
            _fact("revenue", float(i), f"2023-01-{i + 1:02d}", unit="XOF")
            for i in range(28)
        ] + [
            _fact("costs", float(i), f"2024-06-{i + 1:02d}", unit="XOF")
            for i in range(28)
        ]
        [result] = engine.run(facts, ["correlation"])
        assert result["output"]["sufficient_data"] is False


class TestUnknownTypeStub:
    def test_unknown_type_stubbed(self, engine):
        [result] = engine.run([], ["alchemy"])
        assert result["output"] == {
            "sufficient_data": False,
            "message": "analysis not enabled in this phase",
        }

    def test_mixed_run_dispatches_each_type(self, engine):
        facts = [_fact("revenue", 10.0, "2023")]
        results = engine.run(facts, ["descriptive", "anomaly"])
        assert [r["analysis_type"] for r in results] == ["descriptive", "anomaly"]
        # The single-fact anomaly run is a real (insufficient-data) result,
        # not a stub.
        assert results[1]["output"]["metrics"][0]["sufficient_data"] is False
        assert results[1]["output"]["metrics"][0]["message"] == (
            "no significant anomaly detected"
        )
