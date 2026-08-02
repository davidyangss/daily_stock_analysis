# -*- coding: utf-8 -*-
"""Optional iWencai OpenAPI adapter for structured strategy data.

The gateway returns query-dependent, date-suffixed columns.  This module keeps
that unstable shape behind small normalized capability methods and never reads
credentials from anywhere except the runtime configuration/environment.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .realtime_types import RealtimeSource, UnifiedRealtimeQuote

logger = logging.getLogger(__name__)

_API_URL = "https://openapi.iwencai.com/v1/query2data"
_SKILL_VERSION = "1.0.0"


def _column_key(value: Any) -> str:
    return re.sub(r"[\s_\-（）()\[\]【】:]", "", str(value or "")).lower()


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text.lower() in {"-", "--", "none", "null", "nan"}:
        return None
    multiplier = 1.0
    for suffix, factor in (("万亿", 1e12), ("亿", 1e8), ("万", 1e4)):
        if text.endswith(suffix):
            multiplier = factor
            text = text[: -len(suffix)]
            break
    try:
        return float(text) * multiplier
    except (TypeError, ValueError):
        return None


def _pick(row: Mapping[str, Any], aliases: Iterable[str]) -> Any:
    normalized_aliases = [_column_key(alias) for alias in aliases]
    # Prefer exact semantic matches before date-suffixed/qualified columns.
    for key, value in row.items():
        normalized = _column_key(key)
        if normalized in normalized_aliases and value not in (None, "", "-", "--"):
            return value
    for key, value in row.items():
        normalized = _column_key(key)
        if any(alias in normalized for alias in normalized_aliases) and value not in (None, "", "-", "--"):
            return value
    return None


def _pick_excluding(row: Mapping[str, Any], aliases: Iterable[str], excluded: Iterable[str]) -> Any:
    excluded_keys = [_column_key(item) for item in excluded]
    filtered = {
        key: value
        for key, value in row.items()
        if not any(item in _column_key(key) for item in excluded_keys)
    }
    return _pick(filtered, aliases)


def _code_matches(row: Mapping[str, Any], stock_code: str) -> bool:
    raw = _pick(row, ("股票代码", "证券代码", "代码"))
    if raw is None:
        return True
    returned = re.sub(r"\D", "", str(raw).split(".", 1)[0])
    expected = re.sub(r"\D", "", stock_code)
    return returned.lstrip("0") == expected.lstrip("0")


def _capital_flow_window_values(row: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    """Parse iWencai's real single-date/date-range capital-flow columns."""
    single = None
    ranges = []
    for key, value in row.items():
        normalized = _column_key(key)
        if "主力资金流向" not in normalized and "主力净流入" not in normalized:
            continue
        match = re.search(r"\[(\d{8})(?:-(\d{8}))?\]", str(key))
        if not match:
            continue
        if match.group(2) is None:
            single = value
            continue
        try:
            start = datetime.strptime(match.group(1), "%Y%m%d")
            end = datetime.strptime(match.group(2), "%Y%m%d")
            ranges.append(((end - start).days, value))
        except ValueError:
            continue
    ranges.sort(key=lambda item: item[0])
    five_day = ranges[0][1] if ranges else None
    ten_day = ranges[1][1] if len(ranges) > 1 else None
    return single, five_day, ten_day


def _dated_metric_date(row: Mapping[str, Any], aliases: Iterable[str]) -> Optional[str]:
    normalized_aliases = [_column_key(alias) for alias in aliases]
    dates = []
    for key in row:
        normalized = _column_key(key)
        if not any(alias in normalized for alias in normalized_aliases):
            continue
        dates.extend(re.findall(r"\[(\d{8})\]", str(key)))
    return max(dates) if dates else None


def _text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "-", "--", "none", "null", "nan"} else text


def _display_number(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.4f}".rstrip("0").rstrip(".")


def _quick_report_summary(row: Mapping[str, Any]) -> Optional[str]:
    """Build a summary only when the payload proves it came from a quick report."""
    provenance = " ".join(
        f"{key} {_text(value)}" for key, value in row.items()
        if "来源" in str(key) or "说明" in str(key) or "报告类型" in str(key)
    )
    quick_keys = " ".join(str(key) for key in row if "快报" in str(key))
    if "快报" not in f"{quick_keys} {provenance}":
        return None

    report_date = _text(_pick(row, ("业绩快报公告日期", "公告日期", "报告日期", "最新报告期")))
    revenue = _number(_pick(row, ("业绩快报营业收入", "营业收入")))
    revenue_yoy = _number(_pick(row, ("业绩快报营业收入同比增长率", "营业收入同比增长率")))
    profit = _number(_pick(row, ("业绩快报归母净利润", "业绩快报净利润", "归母净利润")))
    profit_yoy = _number(_pick(row, ("业绩快报归母净利润同比增长率", "归母净利润同比增长率")))
    parts = []
    if revenue is not None:
        parts.append(f"营业收入{_display_number(revenue)}元")
    if revenue_yoy is not None:
        parts.append(f"营收同比{revenue_yoy:g}%")
    if profit is not None:
        parts.append(f"归母净利润{_display_number(profit)}元")
    if profit_yoy is not None:
        parts.append(f"归母净利润同比{profit_yoy:g}%")
    if not parts:
        return None
    return f"{report_date + '：' if report_date else ''}{'，'.join(parts)}"


def _top10_holder_change_summary(rows: Iterable[Mapping[str, Any]]) -> Optional[str]:
    """Normalize iWencai's multi-row top-shareholder change response."""
    changes = []
    for row in rows:
        change_type = _text(_pick(row, ("持股变动类型", "变动类型")))
        quantity_change = _number(_pick(row, ("持股数量变动", "持股数变动")))
        ratio_change = _number(_pick(row, ("持股比例变动", "持股占比变动")))
        if not change_type and quantity_change is None and ratio_change is None:
            continue
        changes.append({
            "date": _text(_pick(row, ("公告日期", "报告日期", "截止日期"))),
            "type": change_type,
            "quantity": quantity_change,
            "ratio": ratio_change,
        })
    if not changes:
        return None

    latest_date = max((item["date"] for item in changes if item["date"]), default="")
    latest = [item for item in changes if not latest_date or item["date"] in {"", latest_date}]
    type_counts: Dict[str, int] = {}
    for item in latest:
        if item["type"]:
            type_counts[item["type"]] = type_counts.get(item["type"], 0) + 1
    parts = [f"{name}{count}名" for name, count in type_counts.items()]
    quantities = [item["quantity"] for item in latest if item["quantity"] is not None]
    if quantities:
        parts.append(f"已披露持股数量变动合计{_display_number(sum(quantities))}股")
    ratios = [item["ratio"] for item in latest if item["ratio"] is not None]
    if ratios:
        parts.append(f"已披露持股比例变动合计{_display_number(sum(ratios))}个百分点")
    if not parts:
        return None
    return f"{latest_date + '：' if latest_date else ''}{'，'.join(parts)}"


class IwencaiAdapter:
    """Small fail-open client for the official iWencai SkillHub gateway."""

    def __init__(self, api_key: str, timeout: float = 8.0):
        self.api_key = (api_key or "").strip()
        self.timeout = max(0.1, float(timeout))

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def query(self, query: str, *, skill_id: str, limit: int = 10) -> Dict[str, Any]:
        if not self.available:
            raise RuntimeError("IWENCAI_API_KEY is not configured")
        payload = json.dumps({
            "query": query,
            "page": "1",
            "limit": str(max(1, limit)),
            "is_cache": "1",
            "expand_index": "true",
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            _API_URL,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Claw-Call-Type": "normal",
                "X-Claw-Skill-Id": skill_id,
                "X-Claw-Skill-Version": _SKILL_VERSION,
                "X-Claw-Plugin-Id": "none",
                "X-Claw-Plugin-Version": "none",
                "X-Claw-Trace-Id": secrets.token_hex(32),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"iWencai request failed: {type(exc).__name__}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("iWencai returned a non-object response")
        datas = result.get("datas")
        if not isinstance(datas, list):
            message = result.get("message") or result.get("msg") or "missing datas"
            raise RuntimeError(f"iWencai gateway response invalid: {message}")
        return result

    @staticmethod
    def _stock_row(result: Mapping[str, Any], stock_code: str) -> Optional[Mapping[str, Any]]:
        for row in result.get("datas", []):
            if isinstance(row, Mapping) and _code_matches(row, stock_code):
                return row
        return None

    @staticmethod
    def _stock_rows(result: Mapping[str, Any], stock_code: str) -> List[Mapping[str, Any]]:
        return [
            row for row in result.get("datas", [])
            if isinstance(row, Mapping) and _code_matches(row, stock_code)
        ]

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        query = (
            f"{stock_code} 最新价 涨跌幅 涨跌额 成交量 成交额 换手率 量比 振幅 "
            "开盘价 最高价 最低价 昨收 市盈率 市净率 总市值 流通市值"
        )
        row = self._stock_row(self.query(query, skill_id="hithink-market-query", limit=3), stock_code)
        if not row:
            return None
        price = _number(_pick(row, ("最新价", "现价", "收盘价")))
        if price is None or price <= 0:
            return None
        return UnifiedRealtimeQuote(
            code=stock_code,
            name=str(_pick(row, ("股票简称", "证券简称", "名称")) or ""),
            source=RealtimeSource.IWENCAI,
            price=price,
            change_pct=_number(_pick(row, ("涨跌幅",))),
            change_amount=_number(_pick(row, ("涨跌额",))),
            volume=int(value) if (value := _number(_pick(row, ("成交量",)))) is not None else None,
            amount=_number(_pick(row, ("成交额",))),
            volume_ratio=_number(_pick(row, ("量比",))),
            turnover_rate=_number(_pick(row, ("换手率",))),
            amplitude=_number(_pick(row, ("振幅",))),
            open_price=_number(_pick(row, ("开盘价", "今开"))),
            high=_number(_pick(row, ("最高价", "最高"))),
            low=_number(_pick(row, ("最低价", "最低"))),
            pre_close=_number(_pick(row, ("昨收", "前收盘价"))),
            pe_ratio=_number(_pick(row, ("市盈率", "pe"))),
            pb_ratio=_number(_pick(row, ("市净率", "pb"))),
            total_mv=_number(_pick(row, ("总市值",))),
            circ_mv=_number(_pick(row, ("流通市值",))),
        )

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """Resolve an A-share name without requiring a valid realtime price."""
        query = f"{stock_code} 股票简称"
        row = self._stock_row(self.query(query, skill_id="hithink-market-query", limit=1), stock_code)
        if not row:
            return None
        name = _text(_pick(row, ("股票简称", "证券简称", "名称")))
        return name or None

    def get_capital_flow(self, stock_code: str) -> Dict[str, Any]:
        query = f"{stock_code} 当日主力净流入 近5日主力累计净流入 近10日主力累计净流入"
        row = self._stock_row(self.query(query, skill_id="hithink-market-query", limit=3), stock_code)
        if not row:
            return {"status": "not_supported", "stock_flow": {}, "source_chain": [], "errors": []}
        ranged_main, ranged_5d, ranged_10d = _capital_flow_window_values(row)
        main_value = ranged_main if ranged_main is not None else _pick_excluding(
            row,
            ("当日主力净流入", "今日主力净流入", "主力净流入"),
            ("近5日", "5日", "近10日", "10日"),
        )
        five_day_value = ranged_5d if ranged_5d is not None else _pick(
            row, ("近5日主力累计净流入", "5日主力净流入", "5日主力资金净流入")
        )
        ten_day_value = ranged_10d if ranged_10d is not None else _pick(
            row, ("近10日主力累计净流入", "10日主力净流入", "10日主力资金净流入")
        )
        stock_flow = {
            "main_net_inflow": _number(main_value),
            "inflow_5d": _number(five_day_value),
            "inflow_10d": _number(ten_day_value),
        }
        has_data = any(value is not None for value in stock_flow.values())
        return {
            "status": "partial" if has_data else "not_supported",
            "stock_flow": stock_flow if has_data else {},
            "sector_rankings": {"top": [], "bottom": []},
            "source_chain": [{"provider": "iwencai", "result": "partial", "duration_ms": 0}] if has_data else [],
            "errors": [],
        }

    def get_fundamental_bundle(self, stock_code: str) -> Dict[str, Any]:
        query = (
            f"{stock_code} 最新报告期 营业收入 营业收入同比增长率 归母净利润 "
            "归母净利润同比增长率 净资产收益率 毛利率 经营活动现金流量净额 "
            "股东户数变化"
        )
        row = self._stock_row(self.query(query, skill_id="hithink-finance-query", limit=3), stock_code)
        if not row:
            return {"status": "not_supported", "growth": {}, "earnings": {}, "institution": {}, "source_chain": [], "errors": []}
        revenue_yoy = _number(_pick(row, ("营业收入同比增长率", "营收同比增长率", "营业收入同比")))
        profit_yoy = _number(_pick(row, ("归母净利润同比增长率", "净利润同比增长率", "归母净利润同比")))
        roe = _number(_pick(row, ("净资产收益率", "roe")))
        gross_margin = _number(_pick(row, ("毛利率", "销售毛利率")))
        financial_report = {
            "report_date": _pick(row, ("最新报告期", "报告期", "报告日期")) or _dated_metric_date(
                row, ("净资产收益率", "毛利率", "经营活动产生的现金流量净额")
            ),
            "revenue": _number(_pick(row, ("营业收入", "营业总收入"))),
            "net_profit_parent": _number(_pick(row, ("归母净利润", "归属于母公司股东的净利润"))),
            "operating_cash_flow": _number(_pick(row, (
                "经营活动产生的现金流量净额", "经营活动现金流量净额", "经营现金流",
            ))),
            "roe": roe,
        }
        growth = {
            "revenue_yoy": revenue_yoy,
            "net_profit_yoy": profit_yoy,
            "roe": roe,
            "gross_margin": gross_margin,
        }
        institution = {
            "shareholder_count_change": _number(_pick(row, (
                "总户数较上期变动", "总户数较上期增长率", "股东户数变化", "股东户数增减",
            ))),
        }
        earnings = (
            {"financial_report": financial_report}
            if any(value is not None for value in financial_report.values()) else {}
        )
        errors = []
        missing_reasons: Dict[str, str] = {}
        quick_query = (
            f"{stock_code} 最新业绩快报 业绩快报营业收入 业绩快报归母净利润 "
            "业绩快报营业收入同比增长率 业绩快报归母净利润同比增长率 业绩快报公告日期"
        )
        try:
            quick_row = self._stock_row(
                self.query(quick_query, skill_id="hithink-finance-query", limit=3), stock_code
            )
            quick_summary = _quick_report_summary(quick_row or {})
            if not quick_summary:
                missing_reasons["earnings.quick_report_summary"] = "no_matching_quick_report"
        except Exception as exc:
            quick_summary = None
            errors.append(f"earnings_quick:iwencai:{type(exc).__name__}")
            missing_reasons["earnings.quick_report_summary"] = "quick_report_fetch_failed"
        # Keep this query deliberately narrow. Adding requested output columns
        # makes iWencai reinterpret it as the current top-10 holding total and
        # drops the change-detail rows.
        top10_query = f"{stock_code} 前十大股东持股数量变动"
        try:
            top10_rows = self._stock_rows(
                self.query(top10_query, skill_id="hithink-finance-query", limit=10), stock_code
            )
            top10_summary = _top10_holder_change_summary(top10_rows)
            if not top10_summary:
                missing_reasons["institution.top10_holder_change"] = "no_top10_holder_change"
        except Exception as exc:
            top10_summary = None
            errors.append(f"top10:iwencai:{type(exc).__name__}")
            missing_reasons["institution.top10_holder_change"] = "top10_holder_change_fetch_failed"
        if quick_summary:
            earnings["quick_report_summary"] = quick_summary
        if top10_summary:
            institution["top10_holder_change"] = top10_summary
        growth = {key: value for key, value in growth.items() if value is not None}
        institution = {key: value for key, value in institution.items() if value is not None}
        has_data = bool(growth or earnings or institution)
        return {
            "status": "partial" if has_data else "not_supported",
            "growth": growth,
            "earnings": earnings,
            "institution": institution,
            "source_chain": [{"provider": "iwencai", "result": "partial", "duration_ms": 0}] if has_data else [],
            "errors": errors,
            "missing_reasons": missing_reasons,
        }
