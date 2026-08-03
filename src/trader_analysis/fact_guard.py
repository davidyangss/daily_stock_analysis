"""Deterministic corrections for evidence-backed facts in public reports."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from src.trader_analysis.market_facts import build_market_facts
from src.trader_analysis.schemas.evidence import (
    EvidenceIssue,
    EvidenceIssueSeverity,
    EvidenceLedger,
)


_MONTH_LOW_RETURN = re.compile(
    r"(?P<prefix>距\s*(?P<month>\d{1,2})\s*月低点约\s*)[+＋]?\d+(?:\.\d+)?\s*%"
)
_LOW_REBOUND = re.compile(
    r"自\s*(?P<low>\d+(?:\.\d+)?)\s*元?低点反弹(?:至)?\s*"
    r"(?P<current>\d+(?:\.\d+)?)\s*元?\s*[（(](?P<detail>[^）)]+)[）)]"
)
_MACD_ZERO_CROSS = re.compile(
    r"(?P<prefix>(?:MACD\s*)?DIF[^。；\n]{0,40}?(?:于\s*)?)"
    r"(?P<date>\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日)"
    r"(?P<suffix>\s*(?:突破|上穿)零轴(?:上方)?)",
    re.IGNORECASE,
)
_SMA_200_CLAIM = re.compile(
    r"[^\n。；]*200\s*日(?:简单移动平均线|均线|SMA)[^\n。；]*(?:[。；]|$)",
    re.IGNORECASE | re.MULTILINE,
)
_LOW_RELATION = re.compile(
    r"低于\s*(?P<label>[^，。；（）()\n]{0,24}?低点)\s*"
    r"(?P<low>\d+(?:\.\d+)?)\s*(?:元)?\s*与现价\s*"
    r"(?P<current>\d+(?:\.\d+)?)"
)
_PLAN_AFTER_RELATION = re.compile(r"即约\s*(?P<plan>\d+(?:\.\d+)?)")
_FLOW_CLAIM = re.compile(
    r"(?P<prefix>(?:(?:近\s*)?\d+\s*(?:个交易)?日|本周|当日|单日|"
    r"主力|游资|散户)?[^，。；\n]{0,24}?(?:主力|游资|散户|资金)?"
    r"[^，。；\n]{0,12}?净(?:流入|流出)\s*)"
    r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>万|亿)元?"
)


def _flow_value(amount: str, unit: str) -> int:
    multiplier = 100_000_000 if unit == "亿" else 10_000
    return round(float(amount) * multiplier)


def _flow_window(prefix: str) -> str:
    recent = re.search(r"近\s*(\d+)\s*(?:个交易)?日", prefix)
    if recent:
        return f"recent_{recent.group(1)}"
    if "本周" in prefix:
        return "week"
    if "当日" in prefix or "单日" in prefix:
        return "day"
    return "unspecified"


def _verified_flow_claims(ledger: EvidenceLedger) -> dict[int, set[str]]:
    claims: dict[int, set[str]] = {}
    for envelope in ledger.envelopes.values():
        text = json.dumps(envelope.payload or {}, ensure_ascii=False, default=str)
        for match in _FLOW_CLAIM.finditer(text):
            value = _flow_value(match.group("amount"), match.group("unit"))
            claims.setdefault(value, set()).add(_flow_window(match.group("prefix")))
    return claims


def _guard_text(
    content: str,
    *,
    facts: Mapping[str, Any],
    verified_flows: Mapping[int, set[str]],
    location: str,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    corrections: list[dict[str, Any]] = []
    unsupported_flows: list[dict[str, Any]] = []
    month_low = facts.get("calendar_month_low") or {}
    if month_low.get("return_to_current_pct") is not None:
        expected = float(month_low["return_to_current_pct"])
        fact_month = str(facts.get("calendar_month") or "")[-2:]

        def replace_month(match: re.Match[str]) -> str:
            if match.group("month").zfill(2) != fact_month:
                return match.group(0)
            replacement = f"{match.group('prefix')}+{expected:.2f}%"
            if replacement != match.group(0):
                corrections.append({
                    "location": location,
                    "kind": "calendar_month_low_return",
                    "original": match.group(0),
                    "replacement": replacement,
                })
            return replacement

        content = _MONTH_LOW_RETURN.sub(replace_month, content)

    def replace_rebound(match: re.Match[str]) -> str:
        low = float(match.group("low"))
        current = float(match.group("current"))
        expected = ((current / low) - 1) * 100 if low else 0.0
        percentages = [float(value) for value in re.findall(r"[+＋]?(\d+(?:\.\d+)?)\s*%", match.group("detail"))]
        if any(abs(value - expected) <= 0.02 for value in percentages):
            return match.group(0)
        replacement = (
            f"自 {low:g} 元低点反弹至 {current:g} 元"
            f"（按上述价位计算 +{expected:.2f}%）"
        )
        corrections.append({
            "location": location,
            "kind": "low_rebound_return",
            "original": match.group(0),
            "replacement": replacement,
        })
        return replacement

    content = _LOW_REBOUND.sub(replace_rebound, content)

    zero_cross = str(facts.get("macd_zero_cross_date") or "")
    zero_cross_dates = {
        str(value)[5:] if len(str(value)) >= 10 else str(value)
        for value in facts.get("macd_zero_cross_dates") or []
    }
    if zero_cross:
        canonical_date = zero_cross[5:] if len(zero_cross) >= 10 else zero_cross

        def replace_cross(match: re.Match[str]) -> str:
            original_date = match.group("date").replace("月", "-").replace("日", "").replace("/", "-")
            original_date = "-".join(part.zfill(2) for part in original_date.split("-"))
            if original_date in zero_cross_dates:
                return match.group(0)
            replacement = f"{match.group('prefix')}{canonical_date}{match.group('suffix')}"
            corrections.append({
                "location": location,
                "kind": "macd_zero_cross_date",
                "original": match.group(0),
                "replacement": replacement,
            })
            return replacement

        content = _MACD_ZERO_CROSS.sub(replace_cross, content)
    else:
        def remove_cross(match: re.Match[str]) -> str:
            replacement = "DIF在连续口径窗口内未确认突破零轴"
            corrections.append({
                "location": location,
                "kind": "unsupported_macd_zero_cross",
                "original": match.group(0),
                "replacement": replacement,
            })
            return replacement

        content = _MACD_ZERO_CROSS.sub(remove_cross, content)

    if facts.get("sma_200_status") != "ok":
        def remove_sma_200_claim(match: re.Match[str]) -> str:
            if re.search(r"不可用|不足|无法计算|不作为", match.group(0)):
                return match.group(0)
            replacement = (
                "| 200日SMA | 不可用 | 连续口径历史不足，不作为趋势依据 |"
                if "|" in match.group(0)
                else "200日SMA：连续口径历史不足，本次不可用，不作为趋势、压力或折溢价依据。"
            )
            corrections.append({
                "location": location,
                "kind": "unavailable_sma_200_claim",
                "original": match.group(0),
                "replacement": replacement,
            })
            return replacement

        content = _SMA_200_CLAIM.sub(remove_sma_200_claim, content)

    def replace_low_relation(match: re.Match[str]) -> str:
        tail = content[match.end():match.end() + 80]
        plan_match = _PLAN_AFTER_RELATION.search(tail)
        if plan_match is None:
            return match.group(0)
        low = float(match.group("low"))
        current = float(match.group("current"))
        plan = float(plan_match.group("plan"))
        if plan < low:
            return match.group(0)
        relation = (
            f"高于 {match.group('label')} {low:g} 元、低于现价 {current:g}"
            if plan < current
            else f"不低于 {match.group('label')} {low:g} 元及现价 {current:g}"
        )
        corrections.append({
            "location": location,
            "kind": "stop_reference_relation",
            "original": match.group(0),
            "replacement": relation,
            "plan": plan,
        })
        return relation

    content = _LOW_RELATION.sub(replace_low_relation, content)

    def replace_flow(match: re.Match[str]) -> str:
        value = _flow_value(match.group("amount"), match.group("unit"))
        window = _flow_window(match.group("prefix"))
        verified_windows = verified_flows.get(value, set())
        if value in verified_flows and (
            window == "unspecified"
            or window in verified_windows
            or "unspecified" in verified_windows
        ):
            return match.group(0)
        replacement = f"{match.group('prefix')}数值未经本次证据核验"
        unsupported_flows.append({
            "location": location,
            "original": match.group(0),
            "replacement": replacement,
        })
        return replacement

    content = _FLOW_CLAIM.sub(replace_flow, content)
    return content, corrections, unsupported_flows


def guard_report_facts(
    state: Mapping[str, Any], ledger: EvidenceLedger,
) -> tuple[dict[str, Any], list[EvidenceIssue]]:
    """Correct bounded market facts and remove unsupported flow claims."""
    daily = ledger.envelopes.get("market_daily_bars")
    snapshot = ledger.envelopes.get("verified_market_snapshot")
    facts = build_market_facts(
        (daily.payload or {}) if daily else {},
        (snapshot.payload or {}) if snapshot else {},
    )
    verified_flows = _verified_flow_claims(ledger)
    corrections: list[dict[str, Any]] = []
    unsupported_flows: list[dict[str, Any]] = []

    def walk(value: Any, location: str) -> Any:
        if isinstance(value, str):
            guarded, found, unsupported = _guard_text(
                value,
                facts=facts,
                verified_flows=verified_flows,
                location=location,
            )
            corrections.extend(found)
            unsupported_flows.extend(unsupported)
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

    guarded_state = walk(state, "state")
    issues: list[EvidenceIssue] = []
    if corrections:
        issues.append(EvidenceIssue(
            code="report_market_fact_corrected",
            severity=EvidenceIssueSeverity.WARNING,
            capability="report_publication",
            provider="deterministic_guard",
            message="公开报告中的行情计算或价位关系与 canonical evidence 不一致，已确定性纠正",
            observed={"corrections": corrections[:20], "count": len(corrections)},
            retriable=False,
        ))
    if unsupported_flows:
        issues.append(EvidenceIssue(
            code="report_unsupported_fund_flow_removed",
            severity=EvidenceIssueSeverity.WARNING,
            capability="report_publication",
            provider="deterministic_guard",
            message="公开报告包含 canonical evidence 未支持的资金流数值，发布时已移除该数值",
            observed={"claims": unsupported_flows[:20], "count": len(unsupported_flows)},
            retriable=False,
        ))
    return guarded_state, issues
