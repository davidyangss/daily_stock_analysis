"""Deterministic market facts derived from one canonical evidence series."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Optional

import pandas as pd


def _number(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def continuous_indicator_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return only the latest price-continuous segment for indicators."""
    rows = [dict(row) for row in payload.get("rows", []) if isinstance(row, Mapping)]
    start_date = str(payload.get("indicator_start_date") or "")
    if payload.get("corporate_action_breaks") and start_date:
        rows = [row for row in rows if str(row.get("trade_date") or "") >= start_date]
    return rows


def build_market_facts(
    daily_payload: Mapping[str, Any],
    snapshot_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build exact values models may quote without doing their own arithmetic."""
    rows = [dict(row) for row in daily_payload.get("rows", []) if isinstance(row, Mapping)]
    eligible_rows = continuous_indicator_rows(daily_payload)
    current_price = _number(snapshot_payload.get("last_price"))
    if current_price is None and rows:
        current_price = _number(rows[-1].get("close"))

    latest_date = str(rows[-1].get("trade_date") or "") if rows else ""
    recent = eligible_rows[-5:]
    recent_low_row = min(
        (row for row in recent if _number(row.get("low")) is not None),
        key=lambda row: float(row["low"]),
        default=None,
    )
    month_rows: list[dict[str, Any]] = []
    try:
        latest_month = date.fromisoformat(latest_date).strftime("%Y-%m")
        month_rows = [
            row for row in eligible_rows
            if str(row.get("trade_date") or "").startswith(latest_month)
        ]
    except ValueError:
        latest_month = ""
    month_low_row = min(
        (row for row in month_rows if _number(row.get("low")) is not None),
        key=lambda row: float(row["low"]),
        default=None,
    )

    def low_fact(row: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
        if row is None:
            return None
        value = _number(row.get("low"))
        rebound = (
            ((current_price / value) - 1) * 100
            if current_price is not None and value not in (None, 0)
            else None
        )
        return {
            "trade_date": row.get("trade_date"),
            "value": value,
            "return_to_current_pct": rebound,
        }

    closes = [_number(row.get("close")) for row in eligible_rows]
    valid_closes = [value for value in closes if value is not None]
    sma_200 = (
        sum(valid_closes[-200:]) / 200
        if len(valid_closes) >= 200
        else None
    )

    macd_zero_cross_date = None
    macd_zero_cross_dates: list[str] = []
    macd_latest = None
    if eligible_rows:
        frame = pd.DataFrame(eligible_rows)
        close = pd.to_numeric(frame.get("close"), errors="coerce")
        dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        valid = pd.DataFrame({"trade_date": frame.get("trade_date"), "dif": dif}).dropna()
        if not valid.empty:
            macd_latest = float(valid.iloc[-1]["dif"])
            crosses = valid[(valid["dif"] > 0) & (valid["dif"].shift(1) <= 0)]
            if not crosses.empty:
                macd_zero_cross_dates = [str(value) for value in crosses["trade_date"].tolist()]
                macd_zero_cross_date = macd_zero_cross_dates[-1]

    return {
        "current_price": current_price,
        "latest_date": latest_date or None,
        "five_day_low": low_fact(recent_low_row),
        "calendar_month": latest_month or None,
        "calendar_month_low": low_fact(month_low_row),
        "sma_200": sma_200,
        "sma_200_status": "ok" if sma_200 is not None else "insufficient_continuous_history",
        "macd_dif_latest": macd_latest,
        "macd_zero_cross_date": macd_zero_cross_date,
        "macd_zero_cross_dates": macd_zero_cross_dates,
        "indicator_start_date": daily_payload.get("indicator_start_date"),
        "corporate_action_breaks": list(daily_payload.get("corporate_action_breaks") or []),
    }
