"""Time-Series Trend Detector Tool.

Takes numeric arrays and returns linear regression, YoY growth, volatility, anomalies.
"""

import logging
import statistics
from typing import Any

logger = logging.getLogger(__name__)


class TrendAnalyzerTool:
    """Tool: Detect trends in time-series numeric data."""

    def analyze(
        self,
        values: list[float],
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Analyze a time-series of numeric values.

        Args:
            values: Ordered numeric values.
            labels: Optional labels (e.g., years) for each value.

        Returns:
            Dict with slope, growth, volatility, anomalies.
        """
        if not values or len(values) < 2:
            return {"error": "At least 2 values required for trend analysis"}

        n = len(values)
        x = list(range(n))

        # Linear regression (simple least squares)
        x_mean = statistics.mean(x)
        y_mean = statistics.mean(values)
        numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
        intercept = y_mean - slope * x_mean

        # YoY growth (if values are annual)
        yoy_growth = []
        for i in range(1, n):
            if values[i - 1] != 0:
                growth = (values[i] - values[i - 1]) / abs(values[i - 1])
                yoy_growth.append(round(growth, 4))
            else:
                yoy_growth.append(None)

        # Volatility (std dev)
        try:
            volatility = statistics.stdev(values)
        except statistics.StatisticsError:
            volatility = 0.0

        # Simple anomaly detection (values beyond 2 std dev)
        anomalies = []
        if volatility > 0:
            for i, v in enumerate(values):
                z_score = (v - y_mean) / volatility if volatility > 0 else 0
                if abs(z_score) > 2:
                    anomalies.append({
                        "index": i,
                        "label": labels[i] if labels else str(i),
                        "value": v,
                        "z_score": round(z_score, 2),
                    })

        # Direction
        direction = "stable"
        if slope > volatility * 0.1:
            direction = "increasing"
        elif slope < -volatility * 0.1:
            direction = "decreasing"

        return {
            "slope": round(slope, 4),
            "intercept": round(intercept, 4),
            "direction": direction,
            "average": round(y_mean, 2),
            "volatility": round(volatility, 2),
            "yoy_growth": yoy_growth,
            "anomalies": anomalies,
            "values": values,
            "labels": labels or [str(i) for i in range(n)],
        }


trend_analyzer = TrendAnalyzerTool()
