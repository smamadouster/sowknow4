"""On-device Chart Renderer Tool.

Produces Vega-Lite JSON specs for line, bar, and pie charts from tables.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ChartGeneratorTool:
    """Tool: Generate Vega-Lite chart specifications."""

    def line_chart(
        self,
        data: list[dict[str, Any]],
        x_field: str,
        y_field: str,
        title: str = "Trend",
        color: str = "#4c78a8",
    ) -> dict[str, Any]:
        """Generate a Vega-Lite line chart spec."""
        return {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": title,
            "width": 600,
            "height": 300,
            "data": {"values": data},
            "mark": {"type": "line", "point": True, "color": color},
            "encoding": {
                "x": {"field": x_field, "type": "ordinal", "title": x_field},
                "y": {"field": y_field, "type": "quantitative", "title": y_field},
                "tooltip": [
                    {"field": x_field, "type": "ordinal"},
                    {"field": y_field, "type": "quantitative"},
                ],
            },
        }

    def bar_chart(
        self,
        data: list[dict[str, Any]],
        x_field: str,
        y_field: str,
        title: str = "Comparison",
        color: str = "#4c78a8",
    ) -> dict[str, Any]:
        """Generate a Vega-Lite bar chart spec."""
        return {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": title,
            "width": 600,
            "height": 300,
            "data": {"values": data},
            "mark": {"type": "bar", "color": color},
            "encoding": {
                "x": {"field": x_field, "type": "ordinal", "title": x_field},
                "y": {"field": y_field, "type": "quantitative", "title": y_field},
                "tooltip": [
                    {"field": x_field, "type": "ordinal"},
                    {"field": y_field, "type": "quantitative"},
                ],
            },
        }

    def pie_chart(
        self,
        data: list[dict[str, Any]],
        field: str,
        category: str,
        title: str = "Distribution",
    ) -> dict[str, Any]:
        """Generate a Vega-Lite pie/donut chart spec."""
        return {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": title,
            "width": 400,
            "height": 400,
            "data": {"values": data},
            "mark": {"type": "arc", "innerRadius": 50},
            "encoding": {
                "theta": {"field": field, "type": "quantitative"},
                "color": {"field": category, "type": "nominal"},
                "tooltip": [
                    {"field": category, "type": "nominal"},
                    {"field": field, "type": "quantitative"},
                ],
            },
        }

    def waterfall_chart(
        self,
        data: list[dict[str, Any]],
        x_field: str,
        y_field: str,
        title: str = "Waterfall",
    ) -> dict[str, Any]:
        """Generate a Vega-Lite waterfall-style bar chart spec."""
        return {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": title,
            "width": 600,
            "height": 300,
            "data": {"values": data},
            "mark": {"type": "bar"},
            "encoding": {
                "x": {"field": x_field, "type": "ordinal", "title": x_field},
                "y": {"field": y_field, "type": "quantitative", "title": y_field},
                "color": {
                    "condition": {"test": f"datum['{y_field}'] >= 0", "value": "#4c78a8"},
                    "value": "#e45756",
                },
                "tooltip": [
                    {"field": x_field, "type": "ordinal"},
                    {"field": y_field, "type": "quantitative"},
                ],
            },
        }


chart_generator = ChartGeneratorTool()
