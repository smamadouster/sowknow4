"""Financial Ratio Engine Tool.

Computes liquidity, solvency, profitability, and efficiency ratios
from balance sheet / income statement tables.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RatioCalculatorTool:
    """Tool: Compute financial ratios from structured tables."""

    def _to_float(self, value: Any) -> float | None:
        """Convert a string/number to float, handling currency symbols and commas."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    def _find_value(self, rows: list[dict], keywords: list[str]) -> float | None:
        """Find a numeric value in table rows by keyword matching."""
        for row in rows:
            for key, val in row.items():
                if any(kw.lower() in str(val).lower() for kw in keywords):
                    # Try other columns for the numeric value
                    for other_key, other_val in row.items():
                        if other_key != key:
                            num = self._to_float(other_val)
                            if num is not None:
                                return num
                if any(kw.lower() in str(key).lower() for kw in keywords):
                    num = self._to_float(val)
                    if num is not None:
                        return num
        return None

    def compute_ratios(self, table: dict[str, Any]) -> dict[str, Any]:
        """Compute standard financial ratios from a balance sheet table."""
        rows = table.get("rows", [])
        if not rows:
            return {"error": "No rows in table"}

        assets = self._find_value(rows, ["total assets", "assets", "actif", "actifs"])
        liabilities = self._find_value(rows, ["total liabilities", "liabilities", "passif", "dettes"])
        equity = self._find_value(rows, ["total equity", "equity", "capitaux propres", "shareholders"])
        current_assets = self._find_value(rows, ["current assets", "actif courant"])
        current_liabilities = self._find_value(rows, ["current liabilities", "passif courant"])
        inventory = self._find_value(rows, ["inventory", "stocks", "inventories"])
        revenue = self._find_value(rows, ["revenue", "turnover", "chiffre d'affaires", "sales"])
        net_income = self._find_value(rows, ["net income", "profit", "résultat net", "bénéfice"])
        debt = self._find_value(rows, ["total debt", "debt", "endettement"])

        ratios = {}

        if current_assets is not None and current_liabilities is not None and current_liabilities != 0:
            ratios["current_ratio"] = round(current_assets / current_liabilities, 2)
        if current_assets is not None and inventory is not None and current_liabilities is not None and current_liabilities != 0:
            ratios["quick_ratio"] = round((current_assets - inventory) / current_liabilities, 2)
        if debt is not None and equity is not None and equity != 0:
            ratios["debt_to_equity"] = round(debt / equity, 2)
        if liabilities is not None and equity is not None and equity != 0:
            ratios["debt_to_equity_alt"] = round(liabilities / equity, 2)
        if net_income is not None and assets is not None and assets != 0:
            ratios["roa"] = round(net_income / assets, 4)
        if net_income is not None and equity is not None and equity != 0:
            ratios["roe"] = round(net_income / equity, 4)
        if net_income is not None and revenue is not None and revenue != 0:
            ratios["net_margin"] = round(net_income / revenue, 4)

        return {
            "extracted_values": {
                k: v for k, v in {
                    "assets": assets,
                    "liabilities": liabilities,
                    "equity": equity,
                    "current_assets": current_assets,
                    "current_liabilities": current_liabilities,
                    "inventory": inventory,
                    "revenue": revenue,
                    "net_income": net_income,
                    "debt": debt,
                }.items() if v is not None
            },
            "ratios": ratios,
        }


ratio_calculator = RatioCalculatorTool()
