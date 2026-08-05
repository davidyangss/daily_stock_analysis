# -*- coding: utf-8 -*-
"""Deterministic, low-sensitivity evidence summaries for Agent tool calls."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Optional


_KEY_VALUE_FIELDS = {
    "price",
    "change_pct",
    "volume",
    "amount",
    "volume_ratio",
    "turnover_rate",
    "amplitude",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "pe_ratio",
    "pb_ratio",
    "total_mv",
    "circ_mv",
    "current_price",
    "ma5",
    "ma10",
    "ma20",
    "ma30",
    "ma60",
    "bias_ma5",
    "trend",
    "trend_status",
    "trend_strength",
    "ma_alignment",
    "volume_status",
    "volume_ratio_5d",
    "volume_ratio_vs_5d",
    "volume_ratio_vs_20d",
    "macd_dif",
    "macd_dea",
    "macd_bar",
    "rsi",
    "rsi_6",
    "rsi_12",
    "rsi_24",
    "buy_signal",
    "signal_score",
    "profit_ratio",
    "avg_cost",
    "concentration",
    "concentration_90",
    "concentration_70",
    "cost_90_low",
    "cost_90_high",
    "main_net_inflow",
    "inflow_5d",
    "inflow_10d",
    "revenue_yoy",
    "net_profit_yoy",
    "roe",
    "gross_margin",
    "industry",
    "sector",
    "market",
}
_SOURCE_FIELDS = ("source", "provider", "data_source", "source_name")
_DATE_FIELDS = ("as_of", "timestamp", "updated_at", "trade_date", "date")
_COUNT_FIELDS = (
    "actual_records",
    "total_records",
    "data_points",
    "result_count",
    "results_count",
    "count",
)

_TOOL_PRESENTATION = {
    "analyze_pattern": (
        "K线形态识别",
        "基于近期日线K线识别十字星、锤头线、吞没、突破和箱体等形态。",
        "近期日线K线（开盘、最高、最低、收盘、成交量）",
    ),
    "analyze_trend": ("技术指标分析", "计算均线、MACD、RSI、支撑阻力和趋势信号。", "近期日线K线与技术指标"),
    "get_daily_history": ("K线数据获取", "获取指定交易日数量的日线OHLCV数据。", "日线K线（开盘、最高、最低、收盘、成交量）"),
    "get_realtime_quote": ("实时行情获取", "获取最新价格、涨跌幅、成交量和估值等行情字段。", "实时行情"),
    "get_volume_analysis": ("量能分析", "分析成交量、量比和量价关系。", "近期日线K线与成交量"),
    "calculate_ma": ("均线计算", "根据日线收盘价计算指定周期均线。", "近期日线K线收盘价"),
    "search_stock_news": ("新闻搜索", "检索与该股票相关的公开新闻和舆情。", "公开新闻与舆情"),
    "search_comprehensive_intel": (
        "综合情报搜索",
        "综合检索最新新闻、公司公告、风险事件、业绩预期和行业趋势。",
        "公开新闻、公告与市场情报",
    ),
    "get_stock_info": ("基本信息获取", "获取股票基础资料及可用基本面字段。", "股票基础资料与基本面"),
    "get_capital_flow": (
        "主力资金流向获取",
        "获取今日及近期主力资金净流入、净流出和相关板块资金排名。",
        "A股主力资金流向",
    ),
    "get_chip_distribution": ("筹码分布分析", "获取成本分布、平均成本和筹码集中度。", "筹码分布数据"),
    "get_sector_rankings": ("行业板块分析", "获取行业或概念板块涨跌排名。", "行业与概念板块行情"),
}

_SOURCE_URLS = {
    "aksharefetcher": "https://www.akshare.xyz/",
    "akshare": "https://www.akshare.xyz/",
    "efinancefetcher": "https://efinance.readthedocs.io/",
    "efinance": "https://efinance.readthedocs.io/",
    "tusharefetcher": "https://tushare.pro/",
    "tushare": "https://tushare.pro/",
    "pytdxfetcher": "https://www.pytdx.org/",
    "pytdx": "https://www.pytdx.org/",
    "baostockfetcher": "http://www.baostock.com/",
    "baostock": "http://www.baostock.com/",
    "yfinancefetcher": "https://finance.yahoo.com/",
    "yfinance": "https://finance.yahoo.com/",
    "finnhubfetcher": "https://finnhub.io/",
    "finnhub": "https://finnhub.io/",
    "alphavantagefetcher": "https://www.alphavantage.co/",
    "alphavantage": "https://www.alphavantage.co/",
    "longbridgefetcher": "https://longbridge.com/",
    "longbridge": "https://longbridge.com/",
    "tencentfetcher": "https://gu.qq.com/",
    "tencent": "https://gu.qq.com/",
    "iwencai": "https://www.iwencai.com/unifiedwap/chat",
    "searxng": "https://docs.searxng.org/",
}

_ZH_EVIDENCE_STATUS_LABELS = {
    "available": "成功",
    "fallback": "已降级",
    "partial": "部分数据",
    "estimated": "估算",
    "stale": "数据过期",
    "missing": "无数据",
    "fetch_failed": "抓取失败",
    "not_supported": "不支持",
}

_METRIC_SPECS: Dict[str, Dict[str, tuple[str, str, str]]] = {
    "get_daily_history": {
        "latest_open": ("最近交易日开盘价", "元", "最近一个交易日的开盘价"),
        "latest_high": ("最近交易日最高价", "元", "最近一个交易日的最高价"),
        "latest_low": ("最近交易日最低价", "元", "最近一个交易日的最低价"),
        "latest_close": ("最近交易日收盘价", "元", "最近一个已完成交易日的收盘价"),
        "latest_volume": ("最近交易日成交量", "股", "最近一个交易日的成交股数"),
        "latest_amount": ("最近交易日成交额", "元", "最近一个交易日的成交金额"),
    },
    "get_volume_analysis": {
        "volume_ratio_vs_5d": ("成交量/近5日均量", "倍", "当前成交量相对近5日平均成交量"),
        "volume_ratio_vs_20d": ("成交量/近20日均量", "倍", "当前成交量相对近20日平均成交量"),
    },
    "analyze_trend": {
        "current_price": ("分析价格", "元", "技术指标计算使用的价格"),
        "ma5": ("5日均线", "元", "最近5个交易日收盘价均值"),
        "ma10": ("10日均线", "元", "最近10个交易日收盘价均值"),
        "ma20": ("20日均线", "元", "最近20个交易日收盘价均值"),
        "ma60": ("60日均线", "元", "最近60个交易日收盘价均值"),
        "bias_ma5": ("相对5日均线乖离率", "%", "价格偏离5日均线的幅度"),
        "macd_dif": ("MACD DIF", "", "短期与长期指数均线差"),
        "macd_dea": ("MACD DEA", "", "DIF的平滑信号线"),
        "macd_bar": ("MACD柱", "", "DIF与DEA差值的动量柱"),
        "rsi_6": ("RSI(6)", "", "6周期相对强弱指标"),
        "rsi_12": ("RSI(12)", "", "12周期相对强弱指标"),
        "rsi_24": ("RSI(24)", "", "24周期相对强弱指标"),
        "signal_score": ("技术信号分", "分", "技术规则汇总后的方向强度评分"),
    },
    "get_chip_distribution": {
        "profit_ratio": ("获利盘比例", "%", "当前价格以下的获利筹码占比"),
        "avg_cost": ("市场平均持仓成本", "元", "筹码分布估算的平均成本"),
        "cost_90_low": ("90%筹码成本下沿", "元", "覆盖90%筹码的成本区间下界"),
        "cost_90_high": ("90%筹码成本上沿", "元", "覆盖90%筹码的成本区间上界"),
        "concentration_90": ("90%筹码集中度", "%", "数值越低通常表示筹码越集中"),
        "concentration_70": ("70%筹码集中度", "%", "核心筹码区间的集中程度"),
    },
    "get_capital_flow": {
        "main_net_inflow": ("当日主力净流入", "元", "主力资金流入减流出的净额"),
        "inflow_5d": ("近5日主力累计净流入", "元", "最近5个交易日主力净流入合计"),
        "inflow_10d": ("近10日主力累计净流入", "元", "最近10个交易日主力净流入合计"),
    },
    "get_realtime_quote": {
        "price": ("最新价", "元", "本次分析使用的最新成交价格"),
        "change_pct": ("涨跌幅", "%", "相对上一交易日收盘价的变化"),
        "volume_ratio": ("量比", "倍", "当前成交速度相对近期平均水平"),
        "turnover_rate": ("换手率", "%", "成交股数占流通股本比例"),
        "pe_ratio": ("市盈率（PE）", "倍", "价格相对盈利水平的估值指标"),
        "pb_ratio": ("市净率（PB）", "倍", "价格相对净资产的估值指标"),
    },
    "get_stock_info": {
        "pe_ratio": ("市盈率（PE）", "倍", "价格相对盈利水平的估值指标"),
        "pb_ratio": ("市净率（PB）", "倍", "价格相对净资产的估值指标"),
        "revenue_yoy": ("营收同比增长率", "%", "营业收入相对上年同期的变化"),
        "net_profit_yoy": ("净利润同比增长率", "%", "归母净利润相对上年同期的变化"),
        "roe": ("净资产收益率（ROE）", "%", "净利润相对股东权益的回报水平"),
        "gross_margin": ("毛利率", "%", "营业收入扣除营业成本后的利润比例"),
    },
}


def canonical_tool_name(value: Any) -> str:
    """Normalize optional MCP/provider prefixes for dependency matching."""
    text = str(value or "").strip()
    return text.rsplit(":", 1)[-1] if ":" in text else text


def _parse_result(result_text: Any) -> Any:
    if isinstance(result_text, (dict, list)):
        return result_text
    if not isinstance(result_text, str):
        return None
    try:
        return json.loads(result_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _safe_text(value: Any, limit: int = 200) -> str:
    return " ".join(str(value or "").split())[:limit]


def _first_text(mapping: Mapping[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return _safe_text(value)
    return None


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _safe_text(value)


def _safe_string_list(value: Any, *, limit: int = 20, item_limit: int = 300) -> List[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: List[str] = []
    for item in value[:limit]:
        text = _safe_text(item, item_limit)
        if text and text not in result:
            result.append(text)
    return result


def _joint_assessment_fields(value: Any) -> tuple[str, List[str], List[str]]:
    """Normalize model-authored joint assessments without leaking Python reprs."""
    if not isinstance(value, Mapping):
        return _safe_text(value, 1000), [], []

    reasoning = _first_text(
        value,
        ("joint_assessment", "assessment", "conclusion", "reasoning", "summary"),
    ) or ""
    decisive_evidence = _safe_string_list(
        value.get("decisive_evidence")
        or value.get("evidence")
        or value.get("key_points"),
        item_limit=500,
    )
    limitations = _safe_string_list(
        value.get("limitations") or value.get("data_limitations"),
        item_limit=500,
    )
    if not limitations:
        limitation = _safe_text(value.get("limitations") or value.get("data_limitations"), 500)
        if limitation:
            limitations = [limitation]
    return reasoning, decisive_evidence, limitations


def _safe_mapping_list(value: Any, *, limit: int = 20) -> List[Dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value[:limit] if isinstance(item, Mapping)]


def _available_evidence_fields(evidence: Mapping[str, Any]) -> set[str]:
    """Return fields that are actually present in one summarized tool result."""
    available = {
        str(key)
        for key, value in (evidence.get("key_values") or {}).items()
        if value not in (None, "", [], {})
    }
    for metric in evidence.get("metric_details") or []:
        if (
            isinstance(metric, Mapping)
            and metric.get("status") == "available"
            and metric.get("key")
        ):
            available.add(str(metric["key"]))
    for field in ("record_count", "as_of", "sources"):
        if evidence.get(field) not in (None, "", [], {}):
            available.add(field)
    return available


def _normalize_joint_assessment(
    value: Any,
    *,
    required_tools: Iterable[str],
    evidence_by_tool: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Validate a new joint assessment against its strategy-owned evidence.

    Plain strings remain readable for legacy reports, but new runtime output is
    not considered completed unless it follows the structured contract and its
    decisive-evidence references can be resolved to available fields.
    """
    required = {
        canonical_tool_name(tool)
        for tool in required_tools or []
        if canonical_tool_name(tool)
    }
    if not isinstance(value, Mapping):
        return {
            "reasoning": _safe_text(value, 1000),
            "status": "invalid",
            "failure_reason": "unstructured_assessment",
            "conditions_met": [],
            "conditions_missed": [],
            "limitations": ["assessment did not use the structured strategy contract"],
            "decisive_evidence": [],
        }

    reasoning = _first_text(
        value,
        ("joint_assessment", "assessment", "conclusion", "reasoning", "summary"),
    ) or ""
    signal = _safe_text(value.get("signal"), 80).lower()
    valid_signals = {"strong_buy", "buy", "hold", "sell", "strong_sell"}
    confidence_raw = value.get("confidence")
    confidence_valid = (
        isinstance(confidence_raw, (int, float))
        and not isinstance(confidence_raw, bool)
        and math.isfinite(float(confidence_raw))
        and 0.0 <= float(confidence_raw) <= 1.0
    )
    limitations = _safe_string_list(
        value.get("limitations") or value.get("data_limitations"),
        item_limit=500,
    )
    conditions_met = _safe_string_list(value.get("conditions_met"), item_limit=500)
    conditions_missed = _safe_string_list(value.get("conditions_missed"), item_limit=500)

    decisive_evidence: List[Dict[str, Any]] = []
    invalid_references: List[str] = []
    for raw_reference in _safe_mapping_list(value.get("decisive_evidence")):
        tool = canonical_tool_name(raw_reference.get("tool"))
        fields = _safe_string_list(raw_reference.get("fields"), limit=30, item_limit=120)
        summary = _safe_text(raw_reference.get("summary"), 500)
        if not tool or tool not in required:
            invalid_references.append(tool or "missing_tool")
            continue
        owned_evidence = evidence_by_tool.get(tool)
        if not isinstance(owned_evidence, Mapping):
            invalid_references.append(f"{tool}:no_owned_evidence")
            continue
        available_fields = _available_evidence_fields(owned_evidence)
        unresolved_fields = [field for field in fields if field not in available_fields]
        if not fields or unresolved_fields:
            suffix = ",".join(unresolved_fields) if unresolved_fields else "missing_fields"
            invalid_references.append(f"{tool}:{suffix}")
            continue
        decisive_evidence.append({
            "tool": tool,
            "fields": fields,
            "summary": summary,
        })

    failure_reasons: List[str] = []
    if not reasoning:
        failure_reasons.append("missing_joint_assessment")
    if signal not in valid_signals:
        failure_reasons.append("invalid_signal")
    if not confidence_valid:
        failure_reasons.append("invalid_confidence")
    if required and not decisive_evidence:
        failure_reasons.append("unverified_decisive_evidence")
    if invalid_references:
        failure_reasons.append("invalid_evidence_reference")
        limitations.append(
            "unresolved decisive evidence: " + "; ".join(invalid_references[:10])
        )

    normalized: Dict[str, Any] = {
        "reasoning": reasoning,
        "status": "invalid" if failure_reasons else "completed",
        "conditions_met": conditions_met,
        "conditions_missed": conditions_missed,
        "limitations": list(dict.fromkeys(limitations))[:20],
        "decisive_evidence": decisive_evidence,
    }
    if signal in valid_signals:
        normalized["signal"] = signal
    if confidence_valid:
        normalized["confidence"] = _safe_confidence(confidence_raw)
    if failure_reasons:
        normalized["failure_reason"] = ",".join(dict.fromkeys(failure_reasons))
    return normalized


def _safe_confidence(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        confidence = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(confidence):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _skill_id_from_agent(value: Any) -> str:
    agent_name = str(value or "").strip()
    for prefix in ("skill_", "skill:", "strategy_"):
        if agent_name.startswith(prefix):
            return agent_name[len(prefix):]
    return agent_name


def _normalize_selected_strategies(values: Iterable[Any]) -> List[Dict[str, str]]:
    selected: List[Dict[str, str]] = []
    seen: set[str] = set()
    for value in values or []:
        if isinstance(value, Mapping):
            skill_id = _safe_text(
                value.get("skill_id") or value.get("id") or value.get("name"),
                120,
            )
            skill_name = _safe_text(
                value.get("skill_name")
                or value.get("display_name")
                or value.get("displayName")
                or skill_id,
                160,
            )
        else:
            skill_id = _safe_text(value, 120)
            skill_name = skill_id
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        selected.append({"skill_id": skill_id, "skill_name": skill_name or skill_id})
    return selected[:20]


def _sanitize_overall_decision(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    decision: Dict[str, Any] = {}
    for field in ("signal", "operation_advice", "confidence_label", "reasoning"):
        raw_value = value.get(field)
        if raw_value not in (None, ""):
            decision[field] = _safe_text(raw_value, 1000 if field == "reasoning" else 200)
    confidence = value.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        decision["confidence"] = _safe_confidence(confidence)
    return decision or None


def _strategy_evaluation_from_opinion(opinion: Any) -> Optional[Dict[str, Any]]:
    agent_name = str(getattr(opinion, "agent_name", "") or "")
    # StrategyEngine's deterministic consensus is an aggregate, not a fourth
    # selected strategy or a separately executed Specialist evaluation.
    from src.agent.skills.defaults import is_skill_consensus_name

    if is_skill_consensus_name(agent_name):
        return None
    skill_id = _skill_id_from_agent(agent_name)
    if not skill_id or not agent_name.startswith(("skill_", "skill:", "strategy_")):
        return None
    raw_data = getattr(opinion, "raw_data", None)
    raw_data = raw_data if isinstance(raw_data, Mapping) else {}
    evidence_status = str(raw_data.get("evidence_status") or "unknown")
    evidence_insufficient = evidence_status == "insufficient"
    evaluation: Dict[str, Any] = {
        "skill_id": skill_id,
        "status": "insufficient" if evidence_insufficient else "completed",
        "evaluation_mode": "specialist",
        "verification_scope": "required_inputs",
        "reasoning": _safe_text(getattr(opinion, "reasoning", ""), 1000),
        "conditions_met": _safe_string_list(raw_data.get("conditions_met")),
        "conditions_missed": _safe_string_list(raw_data.get("conditions_missed")),
        "evidence_status": evidence_status,
    }
    if not evidence_insufficient:
        evaluation["signal"] = _safe_text(getattr(opinion, "signal", ""), 80)
        evaluation["confidence"] = _safe_confidence(getattr(opinion, "confidence", 0.0))
    score_adjustment = raw_data.get("score_adjustment")
    if isinstance(score_adjustment, (int, float)) and not isinstance(score_adjustment, bool):
        evaluation["score_adjustment"] = score_adjustment
    return evaluation


def _strategy_evaluation_from_invalid_record(record: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    from src.agent.skills.defaults import is_skill_consensus_name

    if is_skill_consensus_name(str(record.get("agent_name") or "")):
        return None
    skill_id = _skill_id_from_agent(record.get("agent_name"))
    if not skill_id:
        return None
    reason = str(record.get("reason") or "unknown")
    status = {
        "insufficient_required_data": "insufficient",
        "skill_timeout": "failed",
        "skill_error": "failed",
        "missing_signal": "invalid",
        "unrecognized_signal": "invalid",
    }.get(reason, "failed")
    evaluation: Dict[str, Any] = {
        "skill_id": skill_id,
        "status": status,
        "evaluation_mode": "specialist",
        "verification_scope": "required_inputs",
        "reasoning": _safe_text(record.get("reasoning") or record.get("error"), 1000),
        "conditions_met": _safe_string_list(record.get("conditions_met")),
        "conditions_missed": _safe_string_list(record.get("conditions_missed")),
        "failure_reason": reason,
    }
    raw_signal = record.get("raw_signal")
    if raw_signal not in (None, ""):
        evaluation["raw_signal"] = _safe_text(raw_signal, 80)
    return evaluation


def _metric_details(tool_name: str, mapping: Mapping[str, Any]) -> List[Dict[str, Any]]:
    specs = _METRIC_SPECS.get(canonical_tool_name(tool_name), {})
    details: List[Dict[str, Any]] = []
    for key, (label, unit, description) in specs.items():
        value = mapping.get(key)
        status = "available" if value not in (None, "", [], {}) else "missing"
        display_value: Optional[str] = None
        if status == "available":
            display_number = value
            if key in {"profit_ratio", "concentration_90", "concentration_70"} and isinstance(value, (int, float)):
                display_number = value * 100
            if isinstance(display_number, float):
                display_value = f"{display_number:,.2f}"
            elif isinstance(display_number, int) and not isinstance(display_number, bool):
                display_value = f"{display_number:,}"
            else:
                display_value = str(display_number)
            if unit:
                display_value += unit
        details.append({
            "key": key,
            "label": label,
            "status": status,
            "value": _safe_scalar(value),
            "display_value": display_value,
            "unit": unit,
            "description": description,
            "missing_reason": None if status == "available" else "source_field_missing",
        })
    return details


def _result_sources(payload: Any) -> List[str]:
    sources: List[str] = []

    def add(value: Any) -> None:
        text = _safe_text(value, 120)
        if text and text not in sources:
            sources.append(text)

    if isinstance(payload, Mapping):
        for key in _SOURCE_FIELDS:
            add(payload.get(key))
        raw_sources = payload.get("sources")
        if isinstance(raw_sources, list):
            for source in raw_sources[:20]:
                add(source)
        source_chain = payload.get("source_chain")
        if isinstance(source_chain, list):
            for item in source_chain[:20]:
                if isinstance(item, Mapping):
                    add(item.get("provider") or item.get("source"))
        provider_attempts = payload.get("provider_attempts")
        if isinstance(provider_attempts, list):
            for item in provider_attempts[:20]:
                if isinstance(item, Mapping):
                    add(item.get("provider") or item.get("source"))
        raw_results = payload.get("results")
        if isinstance(raw_results, list):
            for item in raw_results[:20]:
                if isinstance(item, Mapping):
                    for key in _SOURCE_FIELDS:
                        add(item.get(key))
        for key in ("fundamental_context", "valuation", "growth", "earnings"):
            nested = payload.get(key)
            if isinstance(nested, Mapping):
                for source in _result_sources(nested):
                    add(source)
    return sources[:10]


def _source_links(sources: Iterable[str]) -> List[Dict[str, str]]:
    """Return public provider home/data pages only; never derive URLs from errors."""
    links: List[Dict[str, str]] = []
    for source in sources:
        name = _safe_text(source, 120)
        url = _SOURCE_URLS.get(name.lower())
        if url and not any(item["url"] == url for item in links):
            links.append({"name": name, "url": url})
    return links


def _failure_attempts(mapping: Mapping[str, Any]) -> List[Dict[str, str]]:
    raw_attempts = mapping.get("provider_attempts")
    if not isinstance(raw_attempts, list):
        return []
    attempts: List[Dict[str, str]] = []
    for raw in raw_attempts[:10]:
        if not isinstance(raw, Mapping) or not raw.get("reason"):
            continue
        attempts.append({
            "provider": _safe_text(raw.get("provider") or "unknown", 120),
            "operation": _safe_text(raw.get("operation") or "get_data", 120),
            "reason": _safe_text(raw.get("reason"), 300),
        })
    return attempts


def _result_count(payload: Any) -> Optional[int]:
    if isinstance(payload, Mapping):
        for key in _COUNT_FIELDS:
            value = payload.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        for key in ("data", "results", "items", "top"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
    if isinstance(payload, list):
        return len(payload)
    return None


def _evidence_status(payload: Any, execution_success: bool) -> str:
    if not execution_success:
        return "fetch_failed"
    if payload is None:
        return "available"
    if isinstance(payload, Mapping):
        if not payload:
            return "missing"
        raw_status = str(payload.get("status") or "").strip().lower()
        error = payload.get("error")
        provider_attempts = payload.get("provider_attempts")
        if isinstance(provider_attempts, list) and any(
            isinstance(attempt, Mapping) and attempt.get("reason")
            for attempt in provider_attempts
        ):
            return "fetch_failed"
        if raw_status in {"not_supported", "unsupported"}:
            return "not_supported"
        if raw_status in {"failed", "error", "fetch_failed"}:
            return "fetch_failed"
        if raw_status in {"missing", "no_data", "empty"}:
            return "missing"
        if raw_status == "stale":
            return "stale"
        if raw_status == "estimated":
            return "estimated"
        if raw_status == "partial":
            return "partial"
        if raw_status == "fallback":
            return "fallback"
        if error:
            error_text = str(error).lower()
            if "not supported" in error_text or "not_supported" in error_text:
                return "not_supported"
            if "no " in error_text and ("available" in error_text or "data" in error_text):
                return "missing"
            return "fetch_failed"
        if payload.get("success") is False:
            return "fetch_failed"
        if payload.get("stale") is True or payload.get("is_stale") is True:
            return "stale"
        if payload.get("partial") is True or payload.get("partial_cache") is True:
            return "partial"
        source = str(payload.get("source") or "").lower()
        if payload.get("fallback") is True or "fallback" in source:
            return "fallback"
        nested_context = payload.get("fundamental_context")
        if isinstance(nested_context, Mapping):
            nested_status = _evidence_status(nested_context, True)
            if nested_status != "available":
                return nested_status
        collection_keys = (
            "data",
            "results",
            "items",
            "indices",
            "sectors",
            "top_sectors",
            "bottom_sectors",
            "dimensions",
        )
        present_collections = [
            payload.get(key) for key in collection_keys if key in payload
        ]
        if present_collections and all(not value for value in present_collections):
            return "missing"
        for count_key in _COUNT_FIELDS:
            if payload.get(count_key) == 0:
                return "missing"
        if "result" in payload and payload.get("result") is None:
            return "missing"
    return "available"


def summarize_tool_result(
    tool_name: str,
    result_text: Any,
    *,
    execution_success: bool,
    cached: bool = False,
) -> Dict[str, Any]:
    """Project one raw result into a report-safe evidence manifest item."""
    payload = _parse_result(result_text)
    mapping = payload if isinstance(payload, Mapping) else {}
    status = _evidence_status(payload, execution_success)
    requested_records = mapping.get("requested_days")
    if requested_records is None:
        requested_records = mapping.get("effective_days")
    key_values = {
        key: _safe_scalar(value)
        for key, value in mapping.items()
        if key in _KEY_VALUE_FIELDS and value is not None
    }
    raw_data = mapping.get("data")
    latest_record = raw_data[-1] if isinstance(raw_data, list) and raw_data else None
    if isinstance(latest_record, Mapping):
        for key in ("open", "high", "low", "close", "volume", "amount"):
            value = latest_record.get(key)
            if value is not None:
                key_values[f"latest_{key}"] = _safe_scalar(value)
    top_sectors = mapping.get("top_sectors")
    top_sector = top_sectors[0] if isinstance(top_sectors, list) and top_sectors else None
    if isinstance(top_sector, Mapping):
        sector_name = top_sector.get("name") or top_sector.get("sector")
        if sector_name:
            key_values["top_sector"] = _safe_scalar(sector_name)
        if top_sector.get("change_pct") is not None:
            key_values["top_sector_change_pct"] = _safe_scalar(
                top_sector.get("change_pct")
            )
    evidence: Dict[str, Any] = {
        "tool": str(tool_name or "").strip(),
        "status": status,
        "sources": _result_sources(payload),
        "cached": bool(cached or mapping.get("cache_hit")),
        "partial": status == "partial",
        "key_values": key_values,
    }
    metric_details = _metric_details(tool_name, {**mapping, **key_values})
    if metric_details:
        # Older/prefetched fundamental contexts may carry a broad ``partial``
        # status because an optional subdomain (for example boards) degraded.
        # Strategy admission for get_stock_info is based on the explicit
        # report-safe metric contract below. Do not emit a false required-data
        # limitation when every one of those fields is present.
        if (
            canonical_tool_name(tool_name) == "get_stock_info"
            and status == "partial"
            and all(item["status"] == "available" for item in metric_details)
        ):
            status = "available"
            evidence["status"] = status
            evidence["partial"] = False
        evidence["metric_details"] = metric_details
        evidence["missing_fields"] = [
            item["key"] for item in metric_details if item["status"] == "missing"
        ]
    tool_key = canonical_tool_name(tool_name)
    presentation = _TOOL_PRESENTATION.get(tool_key)
    if presentation:
        evidence["tool_display_name"] = presentation[0]
        evidence["tool_description"] = presentation[1]
        evidence["data_description"] = _safe_text(
            mapping.get("data_description") or presentation[2]
        )
    elif mapping.get("data_description"):
        evidence["data_description"] = _safe_text(mapping["data_description"])
    source_links = _source_links(evidence["sources"])
    if source_links:
        evidence["source_links"] = source_links
    as_of = _first_text(mapping, _DATE_FIELDS)
    if not as_of and isinstance(latest_record, Mapping):
        as_of = _first_text(latest_record, _DATE_FIELDS)
    if as_of:
        evidence["as_of"] = as_of
    record_count = _result_count(payload)
    if record_count is not None:
        evidence["record_count"] = record_count
    if isinstance(requested_records, int):
        evidence["requested_records"] = requested_records
    if status not in {"available", "fallback", "stale", "partial", "estimated"}:
        errors = mapping.get("errors")
        errors_text = (
            "; ".join(_safe_text(item, 200) for item in errors[:5] if item)
            if isinstance(errors, list)
            else None
        )
        reason = (
            mapping.get("error")
            or mapping.get("missing_reason")
            or errors_text
            or mapping.get("note")
        )
        evidence["missing_reason"] = _safe_text(reason or status, 300)
        attempts = _failure_attempts(mapping)
        if attempts:
            evidence["failure_attempts"] = attempts
        failure_source = mapping.get("failure_source")
        failure_operation = mapping.get("failure_operation")
        failure_reason = mapping.get("failure_reason")
        if failure_source:
            evidence["failure_source"] = _safe_text(failure_source, 120)
        if failure_operation:
            evidence["failure_operation"] = _safe_text(failure_operation, 120)
        if failure_reason:
            evidence["failure_reason"] = _safe_text(failure_reason, 300)
    return evidence


def build_prefetched_context_evidence(context: Any) -> List[Dict[str, Any]]:
    """Summarize pipeline-prefetched inputs that the Agent report actually uses."""
    if not isinstance(context, Mapping):
        return []
    candidates = (
        ("get_realtime_quote", context.get("realtime_quote")),
        ("get_chip_distribution", context.get("chip_distribution")),
        ("analyze_trend", context.get("trend_result")),
    )
    evidence: List[Dict[str, Any]] = []
    for tool_name, payload in candidates:
        if not isinstance(payload, Mapping) or not payload:
            continue
        item = summarize_tool_result(tool_name, payload, execution_success=True)
        item["stage"] = "prefetch"
        item["prefetched"] = True
        evidence.append(item)

    fundamental = context.get("fundamental_context")
    if isinstance(fundamental, Mapping) and fundamental:
        flattened: Dict[str, Any] = {
            "status": fundamental.get("status"),
            "source_chain": fundamental.get("source_chain"),
            "errors": fundamental.get("errors"),
        }
        for block_key in ("valuation", "growth"):
            block = fundamental.get(block_key)
            data = block.get("data") if isinstance(block, Mapping) else None
            if isinstance(data, Mapping):
                flattened.update(data)
        item = summarize_tool_result("get_stock_info", flattened, execution_success=True)
        item["stage"] = "prefetch"
        item["prefetched"] = True
        evidence.append(item)
    return evidence


def _supplement_owned_evidence(
    owned: Mapping[str, Any],
    prefetched: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Supplement one strategy-owned result only with shared prefetch data."""
    result = dict(owned)
    if not isinstance(prefetched, Mapping):
        return result
    status_rank = {
        "available": 6,
        "fallback": 5,
        "estimated": 4,
        "stale": 3,
        "partial": 2,
        "missing": 1,
        "fetch_failed": 0,
        "not_supported": 0,
    }
    incoming_status = str(prefetched.get("status") or "missing")
    existing_status = str(result.get("status") or "missing")
    if status_rank.get(incoming_status, -1) > status_rank.get(existing_status, -1):
        result["status"] = incoming_status
        result["partial"] = bool(prefetched.get("partial"))
        result["cached"] = bool(prefetched.get("cached"))
        for stale_key in (
            "missing_reason", "failure_attempts", "failure_source",
            "failure_operation", "failure_reason",
        ):
            result.pop(stale_key, None)
    result["prefetched"] = True
    key_values = dict(result.get("key_values") or {})
    key_values.update(prefetched.get("key_values") or {})
    result["key_values"] = key_values
    sources = list(result.get("sources") or [])
    for source in prefetched.get("sources") or []:
        if source not in sources:
            sources.append(source)
    result["sources"] = sources[:10]
    metrics = {
        str(metric.get("key")): dict(metric)
        for metric in result.get("metric_details") or []
        if isinstance(metric, Mapping) and metric.get("key")
    }
    for metric in prefetched.get("metric_details") or []:
        if not isinstance(metric, Mapping) or not metric.get("key"):
            continue
        key = str(metric["key"])
        current = metrics.get(key)
        if current is None or (
            current.get("status") == "missing" and metric.get("status") == "available"
        ):
            metrics[key] = dict(metric)
    if metrics:
        result["metric_details"] = list(metrics.values())
        result["missing_fields"] = [
            metric["key"]
            for metric in result["metric_details"]
            if metric.get("status") == "missing"
        ]
    for key in (
        "record_count", "requested_records", "as_of", "data_description",
        "tool_display_name", "tool_description", "source_links",
    ):
        if result.get(key) in (None, "", [], {}) and prefetched.get(key) not in (None, "", [], {}):
            result[key] = prefetched[key]
    return result


def merge_prefetched_evidence(
    manifest: Any,
    prefetched_items: Iterable[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Merge report inputs fetched before Agent tool execution into the manifest."""
    merged = dict(manifest) if isinstance(manifest, Mapping) else {
        "schema_version": "strategy-evidence-v1",
        "status": "verified",
        "items": [],
        "strategy_requirements": [],
        "limitations": [],
    }
    if merged.get("schema_version") != "strategy-evidence-v1":
        return None
    items = [dict(item) for item in merged.get("items") or [] if isinstance(item, Mapping)]
    by_tool = {canonical_tool_name(item.get("tool")): item for item in items}
    status_rank = {
        "available": 6,
        "fallback": 5,
        "estimated": 4,
        "stale": 3,
        "partial": 2,
        "missing": 1,
        "fetch_failed": 0,
        "not_supported": 0,
    }
    prefetched_by_tool: Dict[str, Dict[str, Any]] = {}
    for raw_item in prefetched_items:
        item = dict(raw_item)
        tool = canonical_tool_name(item.get("tool"))
        if not tool:
            continue
        prefetched_by_tool[tool] = item
        existing = by_tool.get(tool)
        if existing is None:
            items.append(item)
            by_tool[tool] = item
            continue
        incoming_status = str(item.get("status") or "missing")
        existing_status = str(existing.get("status") or "missing")
        if status_rank.get(incoming_status, -1) > status_rank.get(existing_status, -1):
            existing["status"] = incoming_status
            existing["partial"] = bool(item.get("partial"))
            existing["cached"] = bool(item.get("cached"))
            for stale_key in (
                "missing_reason", "failure_attempts", "failure_source",
                "failure_operation", "failure_reason",
            ):
                existing.pop(stale_key, None)
        if item.get("prefetched"):
            existing["prefetched"] = True
        existing_values = existing.get("key_values")
        if not isinstance(existing_values, dict):
            existing_values = {}
            existing["key_values"] = existing_values
        existing_values.update(item.get("key_values") or {})
        existing_metrics = existing.get("metric_details")
        incoming_metrics = item.get("metric_details")
        metrics_by_key = {
            metric.get("key"): dict(metric)
            for metric in existing_metrics or []
            if isinstance(metric, Mapping) and metric.get("key")
        }
        for metric in incoming_metrics or []:
            if not isinstance(metric, Mapping) or not metric.get("key"):
                continue
            key = metric["key"]
            current = metrics_by_key.get(key)
            if current is None or (
                current.get("status") == "missing" and metric.get("status") == "available"
            ):
                metrics_by_key[key] = dict(metric)
        if metrics_by_key:
            existing["metric_details"] = list(metrics_by_key.values())
            existing["missing_fields"] = [
                metric["key"]
                for metric in existing["metric_details"]
                if metric.get("status") == "missing"
            ]
        sources = list(existing.get("sources") or [])
        for source in item.get("sources") or []:
            if source not in sources:
                sources.append(source)
        existing["sources"] = sources[:10]
    merged["items"] = items[:60]

    requirements = [
        dict(item)
        for item in merged.get("strategy_requirements") or []
        if isinstance(item, Mapping)
    ]
    limitations = [
        str(item)
        for item in merged.get("limitations") or []
        if str(item).strip()
    ]
    requirement_skill_ids = {
        str(item.get("skill_id") or "") for item in requirements if item.get("skill_id")
    }
    limitations = [
        item
        for item in limitations
        if not any(item.startswith(f"{skill_id}: required data ") for skill_id in requirement_skill_ids)
    ]
    requirements_by_id: Dict[str, Dict[str, Any]] = {}
    for requirement in requirements:
        skill_id = str(requirement.get("skill_id") or "")
        evidence_items: List[Dict[str, Any]] = []
        missing_tools: List[str] = []
        limited_tools: List[str] = []
        for raw_evidence in requirement.get("evidence") or []:
            if not isinstance(raw_evidence, Mapping):
                continue
            tool = canonical_tool_name(raw_evidence.get("tool"))
            # Never use another Specialist's same-named tool result here.
            # Only the strategy's own evidence and the immutable pipeline
            # prefetch are allowed to satisfy this requirement.
            evidence_item = _supplement_owned_evidence(
                raw_evidence,
                prefetched_by_tool.get(tool),
            )
            evidence_items.append(evidence_item)
            evidence_status = str(evidence_item.get("status") or "missing")
            if evidence_status in {"missing", "fetch_failed", "not_supported"}:
                missing_tools.append(tool)
            elif evidence_status in {"fallback", "partial", "estimated", "stale"}:
                limited_tools.append(tool)
        requirement["evidence"] = evidence_items
        requirement["missing_tools"] = missing_tools
        requirement["limited_tools"] = limited_tools
        requirement["status"] = (
            "insufficient" if missing_tools else ("limited" if limited_tools else "verified")
        )
        requirements_by_id[skill_id] = requirement
        limitations.extend(
            f"{skill_id}: required data unavailable ({tool})" for tool in missing_tools
        )
        limitations.extend(
            f"{skill_id}: required data degraded ({tool})" for tool in limited_tools
        )
    merged["strategy_requirements"] = requirements
    merged["limitations"] = list(dict.fromkeys(limitations))[:20]

    evaluations = [
        dict(item)
        for item in merged.get("strategy_evaluations") or []
        if isinstance(item, Mapping)
    ]
    for evaluation in evaluations:
        if evaluation.get("evaluation_mode") != "joint":
            continue
        requirement_status = str(
            requirements_by_id.get(str(evaluation.get("skill_id") or ""), {}).get("status")
            or "unknown"
        )
        evaluation["evidence_status"] = requirement_status
        if requirement_status == "insufficient":
            evaluation["status"] = "insufficient"
        elif evaluation.get("status") not in {"completed", "invalid"}:
            evaluation["status"] = "invalid"
    merged["strategy_evaluations"] = evaluations

    if requirements:
        requirement_statuses = {item.get("status") for item in requirements}
        merged["status"] = (
            "insufficient"
            if "insufficient" in requirement_statuses
            else ("limited" if "limited" in requirement_statuses else "verified")
        )
    else:
        item_statuses = {item.get("status") for item in merged["items"]}
        if item_statuses & {"missing", "fetch_failed", "not_supported"}:
            merged["status"] = "insufficient"
        elif item_statuses & {"fallback", "partial", "estimated", "stale"}:
            merged["status"] = "limited"
        elif item_statuses:
            merged["status"] = "verified"
        elif merged.get("selected_strategies"):
            merged["status"] = "insufficient"
    return merged


def collect_tool_evidence(tool_calls: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Return de-duplicated evidence entries from execution logs."""
    result: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for call in tool_calls or []:
        evidence = call.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        item = dict(evidence)
        key = (
            str(item.get("tool") or ""),
            json.dumps(call.get("arguments") or {}, sort_keys=True, default=str),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def build_strategy_evidence_manifest(
    *,
    tool_evidence: Iterable[Mapping[str, Any]],
    opinions: Iterable[Any],
    invalid_records: Iterable[Mapping[str, Any]],
    selected_strategies: Iterable[Any] = (),
    selected_strategy_requirements: Optional[Mapping[str, Iterable[str]]] = None,
    joint_strategy_assessments: Optional[Mapping[str, Any]] = None,
    overall_decision: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Build the deterministic dashboard/report projection for data dependencies."""
    opinion_list = list(opinions or [])
    invalid_record_list = list(invalid_records or [])
    observed_items = [
        dict(item) for item in tool_evidence or [] if isinstance(item, Mapping)
    ]
    selected = _normalize_selected_strategies(selected_strategies)
    selected_by_id = {item["skill_id"]: item for item in selected}
    strategy_requirements: List[Dict[str, Any]] = []
    seen_skills: set[str] = set()

    for opinion in opinion_list:
        raw_data = getattr(opinion, "raw_data", None)
        if not isinstance(raw_data, Mapping) or "evidence_status" not in raw_data:
            continue
        skill_id = _skill_id_from_agent(getattr(opinion, "agent_name", ""))
        if not skill_id or skill_id in seen_skills:
            continue
        seen_skills.add(skill_id)
        strategy_requirements.append({
            "skill_id": skill_id,
            "status": str(raw_data.get("evidence_status") or "unknown"),
            "missing_tools": list(raw_data.get("missing_required_tools") or []),
            "limited_tools": list(raw_data.get("limited_required_tools") or []),
            "evidence": list(raw_data.get("required_tool_evidence") or []),
        })

    for record in invalid_record_list:
        if not isinstance(record, Mapping) or record.get("reason") != "insufficient_required_data":
            continue
        skill_id = _skill_id_from_agent(record.get("agent_name"))
        if not skill_id or skill_id in seen_skills:
            continue
        seen_skills.add(skill_id)
        strategy_requirements.append({
            "skill_id": skill_id,
            "status": "insufficient",
            "missing_tools": list(record.get("missing_required_tools") or []),
            "limited_tools": list(record.get("limited_required_tools") or []),
            "evidence": list(record.get("required_tool_evidence") or []),
        })

    # Standard/quick Agent modes evaluate requested strategies together instead
    # of scheduling one SkillAgent per strategy. Preserve that distinction while
    # still projecting every strategy's declarative required_tools against the
    # runtime evidence actually collected by the joint analysis.
    declared_requirements = (
        selected_strategy_requirements
        if isinstance(selected_strategy_requirements, Mapping)
        else {}
    )
    observed_by_tool: Dict[str, Dict[str, Any]] = {}
    status_rank = {
        "available": 6,
        "fallback": 5,
        "estimated": 4,
        "stale": 3,
        "partial": 2,
        "missing": 1,
        "fetch_failed": 0,
        "not_supported": 0,
    }
    for item in observed_items:
        tool_name = canonical_tool_name(item.get("tool"))
        if not tool_name:
            continue
        current = observed_by_tool.get(tool_name)
        if current is None or status_rank.get(str(item.get("status")), -1) > status_rank.get(
            str(current.get("status")), -1
        ):
            observed_by_tool[tool_name] = item

    for selected_item in selected:
        skill_id = selected_item["skill_id"]
        if skill_id in seen_skills:
            continue
        required_tools: List[str] = []
        for raw_tool in declared_requirements.get(skill_id, ()) or ():
            tool_name = canonical_tool_name(raw_tool)
            if tool_name and tool_name not in required_tools:
                required_tools.append(tool_name)
        if not required_tools:
            continue

        evidence_items: List[Dict[str, Any]] = []
        missing_tools: List[str] = []
        limited_tools: List[str] = []
        for tool_name in required_tools:
            observed = observed_by_tool.get(tool_name)
            if observed is None:
                observed = summarize_tool_result(
                    tool_name,
                    {
                        "status": "missing",
                        "missing_reason": "required_tool_not_called",
                    },
                    execution_success=True,
                )
            evidence_item = dict(observed)
            evidence_items.append(evidence_item)
            evidence_status = str(evidence_item.get("status") or "missing")
            if evidence_status in {"missing", "fetch_failed", "not_supported"}:
                missing_tools.append(tool_name)
            elif evidence_status in {"fallback", "partial", "estimated", "stale"}:
                limited_tools.append(tool_name)

        requirement_status = (
            "insufficient"
            if missing_tools
            else ("limited" if limited_tools else "verified")
        )
        seen_skills.add(skill_id)
        strategy_requirements.append({
            "skill_id": skill_id,
            "status": requirement_status,
            "missing_tools": missing_tools,
            "limited_tools": limited_tools,
            "evidence": evidence_items,
        })

    required_items: List[Dict[str, Any]] = []
    required_item_positions: Dict[str, int] = {}
    required_tool_names: set[str] = set()
    for requirement in strategy_requirements:
        skill_id = str(requirement.get("skill_id") or "")
        for evidence in requirement.get("evidence") or []:
            if not isinstance(evidence, Mapping):
                continue
            tool_name = canonical_tool_name(evidence.get("tool"))
            if not tool_name:
                continue
            required_tool_names.add(tool_name)
            required_item = dict(evidence)
            required_item["tool"] = tool_name
            required_item["required"] = True
            required_item["required_by"] = [skill_id] if skill_id else []
            fingerprint_payload = {
                key: value
                for key, value in required_item.items()
                if key not in {"required", "required_by", "stage"}
            }
            fingerprint = json.dumps(
                fingerprint_payload,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            existing_position = required_item_positions.get(fingerprint)
            if existing_position is None:
                required_item_positions[fingerprint] = len(required_items)
                required_items.append(required_item)
                continue
            required_by = required_items[existing_position]["required_by"]
            if skill_id and skill_id not in required_by:
                required_by.append(skill_id)

    # Required evidence must come from each strategy's own execution record.
    # A same-named tool called by another Agent cannot satisfy or visually mask
    # a missing dependency. Keep unrelated observed tools as auxiliary context.
    auxiliary_items = [
        item
        for item in observed_items
        if canonical_tool_name(item.get("tool")) not in required_tool_names
    ]
    items = [*required_items, *auxiliary_items]

    evaluations_by_id: Dict[str, Dict[str, Any]] = {}
    for opinion in opinion_list:
        evaluation = _strategy_evaluation_from_opinion(opinion)
        if evaluation is not None:
            evaluations_by_id[evaluation["skill_id"]] = evaluation
    for record in invalid_record_list:
        if not isinstance(record, Mapping):
            continue
        evaluation = _strategy_evaluation_from_invalid_record(record)
        if evaluation is not None:
            evaluations_by_id[evaluation["skill_id"]] = evaluation

    joint_assessments = (
        joint_strategy_assessments
        if isinstance(joint_strategy_assessments, Mapping)
        else {}
    )
    requirements_by_id = {
        str(item.get("skill_id") or ""): item
        for item in strategy_requirements
        if item.get("skill_id")
    }
    for selected_item in selected:
        skill_id = selected_item["skill_id"]
        if skill_id in evaluations_by_id:
            continue
        requirement = requirements_by_id.get(skill_id, {})
        requirement_evidence = {
            canonical_tool_name(item.get("tool")): item
            for item in requirement.get("evidence") or []
            if isinstance(item, Mapping) and canonical_tool_name(item.get("tool"))
        }
        normalized_assessment = _normalize_joint_assessment(
            joint_assessments.get(skill_id),
            required_tools=declared_requirements.get(skill_id, ()) or (),
            evidence_by_tool=requirement_evidence,
        )
        if not normalized_assessment.get("reasoning") and skill_id not in joint_assessments:
            continue
        evidence_status = str(
            requirement.get("status") or "unknown"
        )
        evaluation_status = str(normalized_assessment.get("status") or "invalid")
        if evidence_status == "insufficient":
            evaluation_status = "insufficient"
        evaluation: Dict[str, Any] = {
            "skill_id": skill_id,
            "status": evaluation_status,
            "evaluation_mode": "joint",
            "reasoning": normalized_assessment.get("reasoning") or "",
            "conditions_met": normalized_assessment.get("conditions_met") or [],
            "conditions_missed": normalized_assessment.get("conditions_missed") or [],
            "decisive_evidence": normalized_assessment.get("decisive_evidence") or [],
            "limitations": normalized_assessment.get("limitations") or [],
            "evidence_status": evidence_status,
            "verification_scope": "required_inputs",
        }
        for field in ("signal", "confidence", "failure_reason"):
            if normalized_assessment.get(field) not in (None, ""):
                evaluation[field] = normalized_assessment[field]
        evaluations_by_id[skill_id] = evaluation

    if not selected:
        derived_ids = [
            *[str(item.get("skill_id") or "") for item in strategy_requirements],
            *evaluations_by_id.keys(),
        ]
        selected = _normalize_selected_strategies(derived_ids)
        selected_by_id = {item["skill_id"]: item for item in selected}

    strategy_evaluations: List[Dict[str, Any]] = []
    for selected_item in selected:
        skill_id = selected_item["skill_id"]
        evaluation = dict(evaluations_by_id.pop(skill_id, {}))
        if not evaluation:
            evaluation = {
                "skill_id": skill_id,
                "status": "not_evaluated",
                "conditions_met": [],
                "conditions_missed": [],
            }
        evaluation["skill_name"] = selected_item["skill_name"]
        strategy_evaluations.append(evaluation)
    for skill_id, evaluation in evaluations_by_id.items():
        extra = dict(evaluation)
        extra["skill_name"] = selected_by_id.get(skill_id, {}).get("skill_name", skill_id)
        strategy_evaluations.append(extra)
        if skill_id not in selected_by_id:
            selected.append({"skill_id": skill_id, "skill_name": extra["skill_name"]})

    sanitized_overall_decision = _sanitize_overall_decision(overall_decision)
    if not items and not strategy_requirements and not selected and sanitized_overall_decision is None:
        return None

    limitations: List[str] = []
    for requirement in strategy_requirements:
        skill_id = requirement["skill_id"]
        for tool in requirement.get("missing_tools") or []:
            limitations.append(f"{skill_id}: required data unavailable ({tool})")
        for tool in requirement.get("limited_tools") or []:
            limitations.append(f"{skill_id}: required data degraded ({tool})")

    statuses = {item.get("status") for item in strategy_requirements}
    if not statuses:
        item_statuses = {item.get("status") for item in items}
        if item_statuses & {"missing", "fetch_failed", "not_supported"}:
            statuses.add("insufficient")
        elif item_statuses & {"fallback", "partial", "estimated", "stale"}:
            statuses.add("limited")
        elif item_statuses:
            statuses.add("verified")
        elif selected:
            statuses.add("insufficient")
    status = (
        "insufficient"
        if "insufficient" in statuses
        else ("limited" if "limited" in statuses else "verified")
    )
    return {
        "schema_version": "strategy-evidence-v1",
        "status": status,
        "verification_scope": "required_inputs",
        "selected_strategies": selected,
        "strategy_evaluations": strategy_evaluations[:20],
        "overall_decision": sanitized_overall_decision,
        "items": items[:60],
        "strategy_requirements": strategy_requirements,
        "limitations": list(dict.fromkeys(limitations))[:20],
    }


def extract_strategy_evidence_manifest(*values: Any) -> Optional[Dict[str, Any]]:
    """Extract the deterministic manifest from persisted/current report payloads."""
    for value in values:
        if not isinstance(value, Mapping):
            continue
        candidates = [value]
        dashboard = value.get("dashboard")
        if isinstance(dashboard, Mapping):
            candidates.append(dashboard)
        raw_result = value.get("raw_result")
        if isinstance(raw_result, Mapping):
            candidates.append(raw_result)
            nested_dashboard = raw_result.get("dashboard")
            if isinstance(nested_dashboard, Mapping):
                candidates.append(nested_dashboard)
        for candidate in candidates:
            manifest = candidate.get("strategy_data_evidence")
            if isinstance(manifest, Mapping) and manifest.get("schema_version") == "strategy-evidence-v1":
                return dict(manifest)
    return None


def update_strategy_overall_decision(
    manifest: Any,
    overall_decision: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Replace the public overall decision after downstream guardrails finish."""
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != "strategy-evidence-v1":
        return None
    updated = dict(manifest)
    updated["overall_decision"] = _sanitize_overall_decision(overall_decision)
    return updated


def build_strategy_synthesis_from_manifest(manifest: Any) -> Optional[Dict[str, Any]]:
    """Aggregate validated per-strategy evaluations without another LLM call."""
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != "strategy-evidence-v1":
        return None
    from src.agent.protocols import AgentOpinion
    from src.agent.skills.engine import StrategyEngine, StrategyResultStatus

    opinions: List[AgentOpinion] = []
    for evaluation in manifest.get("strategy_evaluations") or []:
        if not isinstance(evaluation, Mapping) or evaluation.get("status") != "completed":
            continue
        signal = str(evaluation.get("signal") or "").strip().lower()
        confidence = evaluation.get("confidence")
        if signal not in {"strong_buy", "buy", "hold", "sell", "strong_sell"}:
            continue
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            continue
        skill_id = str(evaluation.get("skill_id") or "").strip()
        if not skill_id:
            continue
        opinions.append(AgentOpinion(
            agent_name=f"skill_{skill_id}",
            signal=signal,
            confidence=_safe_confidence(confidence),
            reasoning=_safe_text(evaluation.get("reasoning"), 1000),
            raw_data={
                "conditions_met": list(evaluation.get("conditions_met") or []),
                "conditions_missed": list(evaluation.get("conditions_missed") or []),
                "evidence_status": evaluation.get("evidence_status"),
            },
        ))
    if not opinions:
        return None
    result = StrategyEngine().process(opinions)
    if result.status != StrategyResultStatus.CONSENSUS:
        return result.synthesis_dict
    return result.synthesis_dict


def format_strategy_evidence_markdown(
    manifest: Any,
    report_language: str = "zh",
    *,
    compact: bool = False,
) -> str:
    """Render per-strategy outputs and their owned inputs for report surfaces."""
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != "strategy-evidence-v1":
        return ""
    language = str(report_language or "zh").strip().lower()
    is_zh = not language.startswith(("en", "ko"))
    if language.startswith("en"):
        text = {
            "heading": "Strategy analysis details",
            "overall_evidence": "Overall evidence",
            "strategy": "Strategy",
            "selected": "Selected strategies",
            "output": "Strategy output",
            "input": "Strategy input data",
            "overall_decision": "Overall decision",
            "limitations": "Data limitations",
            "no_input": "No displayable strategy input data was recorded",
            "tool": "Data tool", "status": "Status", "data": "Data requested",
            "values": "Key values", "source": "Source / coverage", "failure": "Failure details",
            "metric": "Metric", "value": "Value", "meaning": "Meaning",
            "available": "Available", "missing": "Missing", "none": "N/A",
            "signal": "Signal", "confidence": "Confidence", "reasoning": "Decision basis",
            "conditions_met": "Conditions met", "conditions_missed": "Conditions missed",
            "condition": "Condition", "condition_status": "Condition status",
            "met": "Met", "missed": "Not met",
            "limitation_status": "Limitation", "required_data": "Still required",
            "current_state": "Current data / failure",
            "required_unavailable": "Required input unavailable",
            "required_degraded": "Required input partially available",
            "action": "Action",
        }
        public_status_labels = {
            "verified": "Verified", "limited": "Limited", "insufficient": "Insufficient",
            "available": "Success", "fallback": "Fallback", "partial": "Partial",
            "estimated": "Estimated", "stale": "Stale", "missing": "No data",
            "fetch_failed": "Fetch failed", "not_supported": "Unsupported",
            "completed": "Completed", "failed": "Failed", "invalid": "Invalid",
            "not_evaluated": "Not separately evaluated", "unknown": "Unknown",
        }
        public_signal_labels = {
            "strong_buy": "Strong buy", "buy": "Buy", "add": "Add", "hold": "Hold",
            "reduce": "Reduce", "sell": "Sell", "strong_sell": "Strong sell",
            "watch": "Watch", "avoid": "Avoid", "alert": "Alert",
        }
        selected_separator = ", "
    elif language.startswith("ko"):
        text = {
            "heading": "전략 분석 상세",
            "overall_evidence": "전체 근거",
            "strategy": "전략",
            "selected": "선택 전략",
            "output": "전략 분석 출력",
            "input": "전략 분석 입력 데이터",
            "overall_decision": "종합 판정",
            "limitations": "데이터 한계",
            "no_input": "표시 가능한 전략 입력 데이터가 기록되지 않음",
            "tool": "데이터 도구", "status": "상태", "data": "수집 데이터",
            "values": "핵심 값", "source": "출처 / 범위", "failure": "실패 상세",
            "metric": "지표", "value": "값", "meaning": "의미",
            "available": "사용 가능", "missing": "누락", "none": "N/A",
            "signal": "판정 신호", "confidence": "신뢰도", "reasoning": "판정 근거",
            "conditions_met": "충족 조건", "conditions_missed": "미충족 조건",
            "condition": "판정 조건", "condition_status": "조건 상태",
            "met": "충족", "missed": "미충족",
            "limitation_status": "제한 상태", "required_data": "추가 필요 데이터",
            "current_state": "현재 데이터 / 실패",
            "required_unavailable": "필수 입력 사용 불가",
            "required_degraded": "필수 입력 일부 사용 가능",
            "action": "조치",
        }
        public_status_labels = {
            "verified": "검증됨", "limited": "데이터 제한", "insufficient": "근거 부족",
            "available": "사용 가능", "fallback": "강등", "partial": "부분 사용",
            "estimated": "추정", "stale": "만료", "missing": "누락",
            "fetch_failed": "수집 실패", "not_supported": "미지원",
            "completed": "완료", "failed": "실행 실패", "invalid": "결과 무효",
            "not_evaluated": "개별 평가 없음", "unknown": "알 수 없음",
        }
        public_signal_labels = {
            "strong_buy": "강력 매수", "buy": "매수", "add": "추가 매수", "hold": "보유/관망",
            "reduce": "축소", "sell": "매도", "strong_sell": "강력 매도",
            "watch": "관찰", "avoid": "회피", "alert": "경고",
        }
        selected_separator = ", "
    else:
        text = {
            "heading": "策略分析详情：策略关键数据与来源",
            "overall_evidence": "总体证据",
            "strategy": "策略",
            "selected": "所选策略",
            "output": "策略分析输出",
            "input": "策略分析输入数据",
            "overall_decision": "综合判定",
            "limitations": "数据限制",
            "no_input": "本次未记录可展示的策略输入数据",
            "tool": "关键数据工具", "status": "状态", "data": "获取内容",
            "values": "关键值", "source": "来源 / 覆盖", "failure": "失败详情",
            "metric": "指标", "value": "数值", "meaning": "含义",
            "available": "可用", "missing": "缺失", "none": "未记录",
            "signal": "判定信号", "confidence": "置信度", "reasoning": "判定依据",
            "conditions_met": "满足条件", "conditions_missed": "未满足条件",
            "condition": "判定条件", "condition_status": "条件状态",
            "met": "满足条件", "missed": "未满足条件",
            "limitation_status": "限制状态", "required_data": "仍需补充的数据",
            "current_state": "当前数据 / 失败情况",
            "required_unavailable": "必需输入数据不可用",
            "required_degraded": "必需输入数据部分可用",
            "action": "操作建议",
        }
        public_status_labels = {
            "verified": "已验证", "limited": "数据受限", "insufficient": "证据不足",
            **_ZH_EVIDENCE_STATUS_LABELS,
            "completed": "已完成", "failed": "执行失败", "invalid": "结果无效",
            "not_evaluated": "未单独评估", "unknown": "未知",
        }
        public_signal_labels = {
            "strong_buy": "强烈买入", "buy": "买入", "add": "加仓", "hold": "持有/观望",
            "reduce": "减仓", "sell": "卖出", "strong_sell": "强烈卖出",
            "watch": "观察", "avoid": "回避", "alert": "警示",
        }
        selected_separator = "、"

    zh_tokens = {
        "concept_rankings": "概念板块排名",
        "concept_ranking": "概念板块排名",
        "expectation_repricing": "预期重估",
        "get_stock_info": "基本信息获取",
        "search_stock_news": "新闻搜索",
        "required_tool_not_called": "本次策略未再次调用该工具",
        "source_field_missing": "数据源未返回该字段",
    }

    def localize(value: Any) -> str:
        result = str(value if value not in (None, "") else text["none"])
        if not is_zh:
            return result
        for token, label in zh_tokens.items():
            result = result.replace(token, label)
        match = re.match(
            r"^([^:]+): required data (unavailable|degraded) \(([^)]+)\)$",
            result,
        )
        if match:
            strategy, state, tool = match.groups()
            state_text = "必需输入数据不可用" if state == "unavailable" else "必需输入数据部分可用"
            return f"{strategy}：{state_text}（{tool}）"
        return result

    def cell(value: Any) -> str:
        return localize(value).replace("|", "\\|").replace("\n", "<br>")

    def public_status(value: Any) -> str:
        status = str(value or "unknown")
        return public_status_labels.get(status, localize(status))

    def public_signal(value: Any) -> str:
        signal = str(value or "")
        return public_signal_labels.get(signal, localize(signal) if signal else text["none"])

    def strategy_label(skill_id: str, *candidates: Any) -> str:
        name = next((str(value).strip() for value in candidates if str(value or "").strip()), skill_id)
        label = localize(name)
        if not is_zh and label != skill_id:
            return f"{label} (`{skill_id}`)"
        return label

    selected = [
        item for item in (manifest.get("selected_strategies") or [])
        if isinstance(item, Mapping) and item.get("skill_id")
    ]
    evaluations = [
        item for item in (manifest.get("strategy_evaluations") or [])
        if isinstance(item, Mapping) and item.get("skill_id")
    ]
    requirements = [
        item for item in (manifest.get("strategy_requirements") or [])
        if isinstance(item, Mapping) and item.get("skill_id")
    ]
    selected_by_id = {str(item["skill_id"]): item for item in selected}
    evaluations_by_id = {str(item["skill_id"]): item for item in evaluations}
    requirements_by_id = {str(item["skill_id"]): item for item in requirements}
    strategy_ids: List[str] = []
    for collection in (selected, requirements, evaluations):
        for item in collection:
            skill_id = str(item.get("skill_id") or "").strip()
            if skill_id and skill_id not in strategy_ids:
                strategy_ids.append(skill_id)

    all_items = [item for item in (manifest.get("items") or []) if isinstance(item, Mapping)]
    has_owned_items = any(item.get("required_by") for item in all_items)
    item_limit = 8 if compact else 20
    metric_limit = 6 if compact else 12

    def strategy_items(skill_id: str) -> List[Mapping[str, Any]]:
        requirement = requirements_by_id.get(skill_id, {})
        owned = [
            item for item in (requirement.get("evidence") or [])
            if isinstance(item, Mapping)
        ]
        if not owned:
            owned = [
                item for item in all_items
                if skill_id in [str(value) for value in (item.get("required_by") or [])]
            ]
        if not owned and (len(strategy_ids) == 1 or not has_owned_items):
            owned = list(all_items)
        present_tools = {canonical_tool_name(item.get("tool")) for item in owned}
        for tool in requirement.get("missing_tools") or []:
            canonical = canonical_tool_name(tool)
            if canonical and canonical not in present_tools:
                owned.append({
                    "tool": canonical,
                    "status": "missing",
                    "sources": [],
                    "key_values": {},
                    "missing_reason": "required_tool_not_called",
                })
                present_tools.add(canonical)
        for tool in requirement.get("limited_tools") or []:
            canonical = canonical_tool_name(tool)
            if canonical and canonical not in present_tools:
                owned.append({
                    "tool": canonical,
                    "status": "partial",
                    "sources": [],
                    "key_values": {},
                    "missing_reason": "source_field_missing",
                })
                present_tools.add(canonical)
        return owned[:item_limit]

    def required_data_text(tool_name: str, evidence_item: Mapping[str, Any]) -> str:
        missing_labels: List[str] = []
        known_keys: set[str] = set()
        for metric in evidence_item.get("metric_details") or []:
            if not isinstance(metric, Mapping) or not metric.get("key"):
                continue
            key = str(metric["key"])
            known_keys.add(key)
            if metric.get("status") != "available":
                label = localize(metric.get("label") or key)
                if label not in missing_labels:
                    missing_labels.append(label)
        for field in evidence_item.get("missing_fields") or []:
            key = str(field)
            if key not in known_keys:
                label = localize(key)
                if label not in missing_labels:
                    missing_labels.append(label)
        if not evidence_item.get("metric_details"):
            key_values = evidence_item.get("key_values") or {}
            for key, (label, _unit, _description) in _METRIC_SPECS.get(tool_name, {}).items():
                if key_values.get(key) in (None, "", [], {}):
                    localized_label = localize(label)
                    if localized_label not in missing_labels:
                        missing_labels.append(localized_label)
        if missing_labels:
            return "、".join(missing_labels) if is_zh else ", ".join(missing_labels)
        presentation = _TOOL_PRESENTATION.get(tool_name)
        description = evidence_item.get("data_description") or (
            presentation[2] if presentation else tool_name
        )
        if str(evidence_item.get("status") or "") == "stale":
            return f"最新{description}" if is_zh else f"Latest {description}"
        return localize(description)

    def current_data_text(evidence_item: Mapping[str, Any]) -> str:
        details = [public_status(evidence_item.get("status"))]
        sources = [str(source) for source in evidence_item.get("sources") or [] if source]
        if sources:
            details.append(", ".join(sources))
        failures: List[str] = []
        for attempt in evidence_item.get("failure_attempts") or []:
            if isinstance(attempt, Mapping):
                failures.append(
                    f"{attempt.get('provider') or 'unknown'}: "
                    f"{attempt.get('reason') or 'unknown'}"
                )
        if not failures and (evidence_item.get("failure_reason") or evidence_item.get("missing_reason")):
            failures.append(str(evidence_item.get("failure_reason") or evidence_item.get("missing_reason")))
        if failures:
            details.append("; ".join(localize(value) for value in failures[:3]))
        return "；".join(details) if is_zh else "; ".join(details)

    def limitation_rows(limitations: Iterable[Any]) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        pattern = re.compile(
            r"^([^:]+): required data (unavailable|degraded) \(([^)]+)\)$"
        )
        for raw_limitation in list(limitations)[:10]:
            limitation = str(raw_limitation)
            match = pattern.match(limitation)
            if not match:
                rows.append({
                    "strategy": text["none"],
                    "status": localize(limitation),
                    "tool": text["none"],
                    "required": text["none"],
                    "current": text["none"],
                })
                continue
            skill_id, state, raw_tool = match.groups()
            tool_name = canonical_tool_name(raw_tool)
            evidence_item = next(
                (
                    item for item in strategy_items(skill_id)
                    if canonical_tool_name(item.get("tool")) == tool_name
                ),
                {},
            )
            presentation = _TOOL_PRESENTATION.get(tool_name)
            tool_label = evidence_item.get("tool_display_name") or (
                presentation[0] if presentation else tool_name
            )
            state_label = (
                text["required_unavailable"]
                if state == "unavailable"
                else text["required_degraded"]
            )
            rows.append({
                "strategy": strategy_label(
                    skill_id,
                    selected_by_id.get(skill_id, {}).get("skill_name"),
                    evaluations_by_id.get(skill_id, {}).get("skill_name"),
                ),
                "status": state_label,
                "tool": localize(tool_label),
                "required": required_data_text(tool_name, evidence_item),
                "current": current_data_text(evidence_item),
            })
        return rows

    def render_input_table(lines: List[str], items: List[Mapping[str, Any]]) -> None:
        if not items:
            lines.extend(["", f"> {text['no_input']}"])
            return
        lines.extend([
            "",
            f"| {text['tool']} | {text['status']} | {text['data']} | {text['values']} | {text['source']} | {text['failure']} |",
            "|------|:------:|------|------|------|------|",
        ])
        metric_groups: List[tuple[str, List[Mapping[str, Any]]]] = []
        for item in items:
            tool_name = canonical_tool_name(item.get("tool")) or str(item.get("tool") or "unknown")
            presentation = _TOOL_PRESENTATION.get(tool_name)
            tool_label = str(item.get("tool_display_name") or (presentation[0] if presentation else tool_name))
            tool_text = localize(tool_label)
            if not is_zh and tool_text != tool_name:
                tool_text = f"{tool_text} (`{tool_name}`)"
            data_description = item.get("data_description") or (presentation[2] if presentation else text["none"])
            values = item.get("key_values") if isinstance(item.get("key_values"), Mapping) else {}
            value_text = ", ".join(
                f"{localize(key)}={localize(value)}" for key, value in list(values.items())[:6]
            ) or text["none"]
            sources = ", ".join(str(value) for value in (item.get("sources") or []) if value) or text["none"]
            source_links = item.get("source_links") if isinstance(item.get("source_links"), list) else []
            link_text = ", ".join(
                f"[{link.get('name') or 'source'}]({link.get('url')})"
                for link in source_links
                if isinstance(link, Mapping) and link.get("url")
            )
            if link_text:
                sources = f"{sources}<br>{link_text}"
            coverage: List[str] = []
            if item.get("as_of"):
                coverage.append(f"as-of={item['as_of']}")
            if isinstance(item.get("record_count"), int):
                coverage.append(f"records={item['record_count']}")
            if isinstance(item.get("requested_records"), int):
                coverage.append(f"requested={item['requested_records']}")
            if item.get("cached"):
                coverage.append("cache")
            if item.get("partial"):
                coverage.append("partial")
            if coverage:
                sources += "<br>" + "; ".join(coverage)
            failures: List[str] = []
            for attempt in item.get("failure_attempts") or []:
                if isinstance(attempt, Mapping):
                    failures.append(
                        f"{attempt.get('provider') or 'unknown'} "
                        f"{attempt.get('operation') or 'get_data'}: "
                        f"{attempt.get('reason') or 'unknown'}"
                    )
            if not failures and (item.get("failure_reason") or item.get("missing_reason")):
                failures.append(str(item.get("failure_reason") or item.get("missing_reason")))
            lines.append(
                f"| {cell(tool_text)} | {cell(public_status(item.get('status')))} | "
                f"{cell(data_description)} | {cell(value_text)} | {cell(sources)} | "
                f"{cell('<br>'.join(failures) if failures else text['none'])} |"
            )
            metrics = [
                metric for metric in (item.get("metric_details") or [])[:metric_limit]
                if isinstance(metric, Mapping)
            ]
            if metrics:
                metric_groups.append((tool_text, metrics))
        for tool_text, metrics in metric_groups:
            lines.extend([
                "",
                f"**{cell(tool_text)} · {text['input']}**",
                "",
                f"| {text['metric']} | {text['status']} | {text['value']} | {text['meaning']} |",
                "|------|:------:|------:|------|",
            ])
            for metric in metrics:
                available = metric.get("status") == "available"
                metric_value = metric.get("display_value") or metric.get("value") if available else "—"
                lines.append(
                    f"| {cell(metric.get('label') or metric.get('key') or 'unknown')} | "
                    f"{cell(text['available'] if available else text['missing'])} | "
                    f"{cell(metric_value)} | {cell(metric.get('description') or text['none'])} |"
                )

    lines = [
        f"### 🔎 {text['heading']}",
        "",
        f"> **{text['overall_evidence']}**：{public_status(manifest.get('status'))}",
    ]
    if selected:
        selected_text = selected_separator.join(
            strategy_label(str(item["skill_id"]), item.get("skill_name"))
            for item in selected[:20]
        )
        lines.append(f"> **{text['selected']}**：{selected_text}")

    for skill_id in strategy_ids[:10]:
        selected_item = selected_by_id.get(skill_id, {})
        evaluation = evaluations_by_id.get(skill_id, {})
        requirement = requirements_by_id.get(skill_id, {})
        label = strategy_label(
            skill_id,
            selected_item.get("skill_name"),
            evaluation.get("skill_name"),
        )
        status = evaluation.get("status") or requirement.get("status") or "not_evaluated"
        confidence = evaluation.get("confidence")
        confidence_text = f"{float(confidence):.0%}" if isinstance(confidence, (int, float)) else text["none"]
        lines.extend([
            "",
            f"#### {label}",
            "",
            f"##### {text['output']}",
            "",
            f"| {text['status']} | {text['signal']} | {text['confidence']} | {text['reasoning']} |",
            "|:------:|:------:|:------:|------|",
            f"| {cell(public_status(status))} | {cell(public_signal(evaluation.get('signal')))} | "
            f"{cell(confidence_text)} | {cell(evaluation.get('reasoning') or text['none'])} |",
        ])
        conditions_met = _safe_string_list(evaluation.get("conditions_met"), limit=10)
        conditions_missed = _safe_string_list(evaluation.get("conditions_missed"), limit=10)
        if conditions_met or conditions_missed:
            lines.extend([
                "",
                f"| {text['condition_status']} | {text['condition']} |",
                "|:------:|------|",
            ])
            lines.extend(
                f"| {text['met']} | {cell(condition)} |"
                for condition in conditions_met
            )
            lines.extend(
                f"| {text['missed']} | {cell(condition)} |"
                for condition in conditions_missed
            )
        lines.extend(["", f"##### {text['input']}"])
        render_input_table(lines, strategy_items(skill_id))

    if not strategy_ids:
        lines.extend(["", f"#### {text['input']}"])
        render_input_table(lines, all_items[:item_limit])

    overall_decision = manifest.get("overall_decision")
    if isinstance(overall_decision, Mapping):
        confidence = overall_decision.get("confidence")
        confidence_text = (
            f"{float(confidence):.0%}"
            if isinstance(confidence, (int, float))
            else overall_decision.get("confidence_label") or text["none"]
        )
        lines.extend([
            "",
            f"#### {text['overall_decision']}",
            "",
            f"- {text['signal']}：{cell(public_signal(overall_decision.get('signal')))}",
            f"- {text['confidence']}：{cell(confidence_text)}",
        ])
        if overall_decision.get("operation_advice"):
            lines.append(f"- {text['action']}：{cell(overall_decision.get('operation_advice'))}")
        if overall_decision.get("reasoning"):
            lines.append(f"- {text['reasoning']}：{cell(overall_decision.get('reasoning'))}")

    limitations = limitation_rows(manifest.get("limitations") or [])
    if limitations:
        lines.extend(["", f"#### ⚠️ {text['limitations']}", ""])
        lines.extend([
            f"| {text['strategy']} | {text['limitation_status']} | {text['tool']} | "
            f"{text['required_data']} | {text['current_state']} |",
            "|------|------|------|------|------|",
        ])
        lines.extend(
            f"| {cell(item['strategy'])} | {cell(item['status'])} | "
            f"{cell(item['tool'])} | {cell(item['required'])} | {cell(item['current'])} |"
            for item in limitations
        )
    return "\n".join(lines)


__all__ = [
    "build_prefetched_context_evidence",
    "build_strategy_evidence_manifest",
    "canonical_tool_name",
    "collect_tool_evidence",
    "extract_strategy_evidence_manifest",
    "format_strategy_evidence_markdown",
    "merge_prefetched_evidence",
    "summarize_tool_result",
    "update_strategy_overall_decision",
]
