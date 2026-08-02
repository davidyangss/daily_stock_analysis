"""Deterministic publication guards for structured trader proposals."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Optional

from src.trader_analysis.schemas.evidence import (
    EvidenceIssue,
    EvidenceIssueSeverity,
    EvidenceLedger,
)


_BOLD_FIELD = re.compile(
    r"^(?P<indent>[ \t]*)\*\*(?P<label>Action|Entry Price|Stop Loss)(?:[:：])?\*\*"
    r"[ \t]*[:：]?[ \t]*(?P<value>.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_PLAIN_FIELD = re.compile(
    r"^(?P<indent>[ \t]*)(?P<label>Action|Entry Price|Stop Loss)[ \t]*[:：][ \t]*"
    r"(?P<value>.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_NUMBER = re.compile(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?")


def _number(value: Any) -> Optional[float]:
    match = _NUMBER.search(str(value or ""))
    if match is None:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _field_value(content: str, label: str) -> str:
    for pattern in (_BOLD_FIELD, _PLAIN_FIELD):
        for match in pattern.finditer(content):
            if match.group("label").lower() == label.lower():
                return match.group("value").strip()
    return ""


def _rename_field(content: str, old_label: str, new_label: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group("label").lower() != old_label.lower():
            return match.group(0)
        return f"{match.group('indent')}**{new_label}**: {match.group('value')}"

    content = _BOLD_FIELD.sub(replace, content)
    return _PLAIN_FIELD.sub(replace, content)


def _guard_content(
    content: str,
    *,
    current_price: float,
    location: str,
) -> tuple[str, list[EvidenceIssue]]:
    action = _field_value(content, "Action")
    if action.lower().startswith("sell") or action.startswith("卖出"):
        content = _rename_field(content, "Entry Price", "Execution Price")

    stop_loss = _number(_field_value(content, "Stop Loss"))
    if stop_loss is None or stop_loss < current_price:
        return content, []

    content = _rename_field(content, "Stop Loss", "Reassessment Price")
    return content, [EvidenceIssue(
        code="trader_stop_loss_reclassified",
        severity=EvidenceIssueSeverity.WARNING,
        capability="trader_plan",
        provider="tradingagents",
        message=(
            f"交易计划将 {stop_loss:g} 元（不低于已核验当前价 {current_price:g} 元）标为多头止损；"
            "发布时已改列为重新评估价格，未将其作为下行退出边界"
        ),
        observed={
            "location": location,
            "action": action or None,
            "current_price": current_price,
            "original_stop_loss": stop_loss,
            "published_field": "reassessment_price",
        },
        retriable=False,
    )]


def guard_trader_proposal(
    state: Mapping[str, Any], ledger: EvidenceLedger,
) -> tuple[dict[str, Any], list[EvidenceIssue]]:
    """Reclassify impossible long stop-loss fields before reports are published.

    The raw model trace remains unchanged for audit.  This function only
    transforms the report state that crosses the repository/publication
    boundary and emits an explicit quality warning for every correction.
    """
    snapshot = ledger.envelopes.get("verified_market_snapshot")
    current_price = _number((snapshot.payload or {}).get("last_price")) if snapshot else None
    if current_price is None or current_price <= 0:
        return dict(state), []

    issues: list[EvidenceIssue] = []

    def walk(value: Any, location: str) -> Any:
        if isinstance(value, str):
            guarded, found = _guard_content(
                value, current_price=current_price, location=location,
            )
            issues.extend(found)
            return guarded
        if isinstance(value, Mapping):
            return {
                key: walk(item, f"{location}.{key}" if location else str(key))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [walk(item, f"{location}[{index}]") for index, item in enumerate(value)]
        if isinstance(value, tuple):
            return tuple(walk(item, f"{location}[{index}]") for index, item in enumerate(value))
        return value

    return walk(state, "state"), issues
