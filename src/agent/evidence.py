# -*- coding: utf-8 -*-
"""Deterministic, low-sensitivity evidence summaries for Agent tool calls."""

from __future__ import annotations

import json
import math
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
    for raw_item in prefetched_items:
        item = dict(raw_item)
        tool = canonical_tool_name(item.get("tool"))
        if not tool:
            continue
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
            evidence_item = dict(by_tool.get(tool) or raw_evidence)
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
        evaluation["status"] = (
            "insufficient" if requirement_status == "insufficient" else "completed"
        )
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
        reasoning, conditions_met, conditions_missed = _joint_assessment_fields(
            joint_assessments.get(skill_id)
        )
        if not reasoning:
            continue
        evidence_status = str(
            requirements_by_id.get(skill_id, {}).get("status") or "unknown"
        )
        evaluations_by_id[skill_id] = {
            "skill_id": skill_id,
            "status": "insufficient" if evidence_status == "insufficient" else "completed",
            "evaluation_mode": "joint",
            "reasoning": reasoning,
            "conditions_met": conditions_met,
            "conditions_missed": conditions_missed,
            "evidence_status": evidence_status,
        }

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


def format_strategy_evidence_markdown(
    manifest: Any,
    report_language: str = "zh",
    *,
    compact: bool = False,
) -> str:
    """Render one low-sensitivity evidence manifest for text report surfaces."""
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != "strategy-evidence-v1":
        return ""
    language = str(report_language or "zh").strip().lower()
    if language.startswith("en"):
        heading = "Strategy analysis details"
        overall_label = "Overall evidence"
        selected_label = "Selected strategies"
        evaluation_heading = "Strategy decisions"
        overall_decision_heading = "Overall decision"
        source_heading = "Data source overview"
        metrics_heading = "Key metrics"
        limitations_heading = "Data limitations"
        headers = ("Status", "Data requested", "Source / coverage")
        metric_headers = ("Metric", "Status", "Value", "Meaning")
        evaluation_headers = ("Strategy", "Status", "Signal / confidence", "Decision basis")
        available_text, missing_text = "Available", "Missing"
        selected_separator = ", "
        condition_labels = ("Conditions met", "Conditions missed")
        decision_labels = ("Signal", "Confidence", "Action", "Decision basis")
        public_status_labels = {
            "verified": "Verified", "limited": "Limited", "insufficient": "Insufficient",
            "completed": "Completed", "failed": "Failed", "invalid": "Invalid",
            "not_evaluated": "Not separately evaluated",
        }
        public_signal_labels = {
            "strong_buy": "Strong buy", "buy": "Buy", "add": "Add", "hold": "Hold",
            "reduce": "Reduce", "sell": "Sell", "strong_sell": "Strong sell",
            "watch": "Watch", "avoid": "Avoid", "alert": "Alert",
        }
    elif language.startswith("ko"):
        heading = "전략 분석 상세"
        overall_label = "전체 근거"
        selected_label = "선택 전략"
        evaluation_heading = "전략 판정"
        overall_decision_heading = "종합 판정"
        source_heading = "데이터 출처 개요"
        metrics_heading = "핵심 지표"
        limitations_heading = "데이터 한계"
        headers = ("상태", "수집 데이터", "출처 / 범위")
        metric_headers = ("지표", "상태", "값", "의미")
        evaluation_headers = ("전략", "상태", "신호 / 신뢰도", "판정 근거")
        available_text, missing_text = "사용 가능", "누락"
        selected_separator = ", "
        condition_labels = ("충족 조건", "미충족 조건")
        decision_labels = ("판정 신호", "신뢰도", "조치", "판정 근거")
        public_status_labels = {
            "verified": "검증됨", "limited": "데이터 제한", "insufficient": "근거 부족",
            "completed": "완료", "failed": "실행 실패", "invalid": "결과 무효",
            "not_evaluated": "개별 평가 없음",
        }
        public_signal_labels = {
            "strong_buy": "강력 매수", "buy": "매수", "add": "추가 매수", "hold": "보유/관망",
            "reduce": "축소", "sell": "매도", "strong_sell": "강력 매도",
            "watch": "관찰", "avoid": "회피", "alert": "경고",
        }
    else:
        heading = "策略分析详情：策略关键数据与来源"
        overall_label = "总体证据"
        selected_label = "所选策略"
        evaluation_heading = "策略判定结果"
        overall_decision_heading = "综合判定"
        source_heading = "数据获取概览"
        metrics_heading = "关键指标"
        limitations_heading = "数据限制"
        headers = ("状态", "获取内容", "来源 / 覆盖")
        metric_headers = ("指标", "状态", "数值", "含义")
        evaluation_headers = ("策略", "状态", "信号 / 置信度", "判定依据")
        available_text, missing_text = "可用", "缺失"
        selected_separator = "、"
        condition_labels = ("满足条件", "未满足条件")
        decision_labels = ("判定信号", "置信度", "操作建议", "判定依据")
        public_status_labels = {
            "verified": "已验证", "limited": "数据受限", "insufficient": "证据不足",
            "completed": "已完成", "failed": "执行失败", "invalid": "结果无效",
            "not_evaluated": "未单独评估",
        }
        public_signal_labels = {
            "strong_buy": "强烈买入", "buy": "买入", "add": "加仓", "hold": "持有/观望",
            "reduce": "减仓", "sell": "卖出", "strong_sell": "强烈卖出",
            "watch": "观察", "avoid": "回避", "alert": "警示",
        }

    def cell(value: Any) -> str:
        return str(value if value not in (None, "") else "N/A").replace("|", "\\|").replace("\n", "<br>")

    def public_status(value: Any) -> str:
        status = str(value or "unknown")
        return public_status_labels.get(status, status)

    def public_signal(value: Any) -> str:
        signal = str(value or "")
        return public_signal_labels.get(signal, signal or "N/A")

    lines = [f"### 🔎 {heading}", "", f"> **{overall_label}**：{public_status(manifest.get('status'))}"]
    selected = [
        item for item in (manifest.get("selected_strategies") or [])
        if isinstance(item, Mapping) and item.get("skill_id")
    ]
    if selected:
        selected_text = selected_separator.join(
            f"{item.get('skill_name') or item['skill_id']} (`{item['skill_id']}`)"
            for item in selected[:20]
        )
        lines.append(f"> **{selected_label}**：{selected_text}")
    for requirement in (manifest.get("strategy_requirements") or [])[:10]:
        if not isinstance(requirement, Mapping):
            continue
        skill_id = str(requirement.get("skill_id") or "").strip()
        if skill_id:
            lines.append(f"> {skill_id}：{public_status(requirement.get('status'))}")

    evaluations = [
        item for item in (manifest.get("strategy_evaluations") or [])
        if isinstance(item, Mapping) and item.get("skill_id")
    ]
    if evaluations:
        lines.extend([
            "",
            f"#### {evaluation_heading}",
            "",
            f"| {evaluation_headers[0]} | {evaluation_headers[1]} | {evaluation_headers[2]} | {evaluation_headers[3]} |",
            "|------|:------:|:------:|------|",
        ])
        for evaluation in evaluations[:10]:
            confidence = evaluation.get("confidence")
            confidence_text = f"{float(confidence):.0%}" if isinstance(confidence, (int, float)) else "N/A"
            signal = public_signal(evaluation.get("signal"))
            reasoning_parts = [str(evaluation.get("reasoning") or "").strip()]
            conditions_met = _safe_string_list(evaluation.get("conditions_met"), limit=5)
            conditions_missed = _safe_string_list(evaluation.get("conditions_missed"), limit=5)
            if conditions_met:
                reasoning_parts.append(f"{condition_labels[0]}: " + "; ".join(conditions_met))
            if conditions_missed:
                reasoning_parts.append(f"{condition_labels[1]}: " + "; ".join(conditions_missed))
            lines.append(
                f"| {cell(evaluation.get('skill_name') or evaluation['skill_id'])} "
                f"(`{cell(evaluation['skill_id'])}`) | {cell(public_status(evaluation.get('status')))} | "
                f"{cell(signal)} / {cell(confidence_text)} | "
                f"{cell('<br>'.join(part for part in reasoning_parts if part))} |"
            )

    overall_decision = manifest.get("overall_decision")
    if isinstance(overall_decision, Mapping):
        confidence = overall_decision.get("confidence")
        confidence_text = (
            f"{float(confidence):.0%}"
            if isinstance(confidence, (int, float))
            else str(overall_decision.get("confidence_label") or "N/A")
        )
        lines.extend([
            "",
            f"#### {overall_decision_heading}",
            "",
            f"- {decision_labels[0]}: {cell(public_signal(overall_decision.get('signal')))}",
            f"- {decision_labels[1]}: {cell(confidence_text)}",
        ])
        if overall_decision.get("operation_advice"):
            lines.append(f"- {decision_labels[2]}: {cell(overall_decision.get('operation_advice'))}")
        if overall_decision.get("reasoning"):
            lines.append(f"- {decision_labels[3]}: {cell(overall_decision.get('reasoning'))}")

    lines.extend([
        "",
        f"#### {source_heading}",
    ])

    item_limit = 8 if compact else 20
    for item in (manifest.get("items") or [])[:item_limit]:
        if not isinstance(item, Mapping):
            continue
        sources = ", ".join(
            str(value) for value in (item.get("sources") or []) if value
        ) or "N/A"
        source_links = item.get("source_links") if isinstance(item.get("source_links"), list) else []
        source_link_text = ", ".join(
            f"[{link.get('name') or 'source'}]({link.get('url')})"
            for link in source_links
            if isinstance(link, Mapping) and link.get("url")
        )
        if source_link_text:
            sources = f"{sources} ({source_link_text})"
        values = item.get("key_values") if isinstance(item.get("key_values"), Mapping) else {}
        value_text = ", ".join(
            f"{key}={value}" for key, value in list(values.items())[:6]
        ) or "N/A"
        coverage: List[str] = []
        if sources != "N/A":
            coverage.append(f"source={sources}")
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
        required_by = ", ".join(
            str(value) for value in (item.get("required_by") or []) if value
        )
        if required_by:
            coverage.append(f"required_by={required_by}")
        failure_attempts = item.get("failure_attempts")
        if isinstance(failure_attempts, list):
            for attempt in failure_attempts[:5]:
                if not isinstance(attempt, Mapping):
                    continue
                coverage.append(
                    "failure="
                    f"{attempt.get('provider') or 'unknown'} "
                    f"{attempt.get('operation') or 'get_data'}: "
                    f"{attempt.get('reason') or 'unknown'}"
                )
        elif item.get("failure_reason") or item.get("missing_reason"):
            coverage.append(
                "reason=" + str(item.get("failure_reason") or item.get("missing_reason"))
            )
        tool_name = str(item.get("tool") or "unknown")
        tool_label = str(item.get("tool_display_name") or tool_name)
        data_description = str(item.get("data_description") or "")
        status = str(item.get("status") or "unknown")
        display_status = _ZH_EVIDENCE_STATUS_LABELS.get(status, status) if language.startswith("zh") else status
        tool_text = f"{tool_label} (`{tool_name}`)" if tool_label != tool_name else f"`{tool_name}`"
        source_and_coverage = sources
        if coverage:
            source_and_coverage += "<br>" + "; ".join(coverage)
        if value_text != "N/A" and not item.get("metric_details"):
            source_and_coverage += f"<br>{value_text}"
        lines.extend([
            "",
            f"##### {tool_text}",
            "",
            f"| {headers[0]} | {headers[1]} | {headers[2]} |",
            "|------|------|------|",
            f"| {cell(display_status)} | {cell(data_description)} | {cell(source_and_coverage)} |",
        ])
        metric_details = item.get("metric_details")
        if isinstance(metric_details, list):
            metric_rows: List[str] = []
            for metric in metric_details[:12]:
                if not isinstance(metric, Mapping):
                    continue
                metric_label = metric.get("label") or metric.get("key") or "unknown"
                if metric.get("status") == "available":
                    metric_value = metric.get("display_value") or metric.get("value")
                    metric_status = available_text
                else:
                    metric_status = missing_text
                    metric_value = "—"
                description = str(metric.get("description") or "").strip()
                metric_rows.append(
                    f"| {cell(metric_label)} | {cell(metric_status)} | "
                    f"{cell(metric_value)} | {cell(description)} |"
                )
            if metric_rows:
                lines.extend([
                    "",
                    f"**{metrics_heading}**",
                    "",
                    f"| {metric_headers[0]} | {metric_headers[1]} | {metric_headers[2]} | {metric_headers[3]} |",
                    "|------|:------:|------:|------|",
                    *metric_rows,
                ])
    limitations = list(manifest.get("limitations") or [])[:10]
    if limitations:
        lines.extend(["", f"#### ⚠️ {limitations_heading}", ""])
        lines.extend(f"- {limitation}" for limitation in limitations)
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
