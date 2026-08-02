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


def _normalize_report_period(value: Any) -> Optional[str]:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 8:
        return None
    try:
        return datetime.strptime(digits, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _pick_metric_with_date(
    row: Mapping[str, Any], aliases: Iterable[str], *, report_type: Optional[str] = None,
) -> tuple[Any, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Return a metric with period and disclosure provenance.

    iWencai sometimes returns an undated ``营业收入``/``归母净利润`` column while
    putting the real report period and disclosure type only in a sibling
    ``*来源说明`` field.  Treating such a value as belonging to another dated
    column in the same row is unsafe, so provenance is resolved before any
    report-level fallback is considered.
    """
    normalized_aliases = [_column_key(alias) for alias in aliases]
    candidates = []
    for key, value in row.items():
        if value in (None, "", "-", "--"):
            continue
        normalized = _column_key(key)
        if "来源说明" in normalized or normalized.endswith("说明"):
            continue
        if any(token in normalized for token in ("同比", "增长率", "占比", "比率")):
            continue
        exact = normalized in normalized_aliases
        if exact or any(alias in normalized for alias in normalized_aliases):
            match = re.search(r"\[(\d{8})\]", str(key))
            column_type = "earnings_forecast" if "业绩预告" in str(key) else report_type
            candidates.append((0 if exact else 1, value, match.group(1) if match else None, column_type))
    if not candidates:
        return None, None, None, None, None
    candidates.sort(key=lambda item: item[0])
    _, value, period, disclosure_type = candidates[0]

    source = ""
    for key, candidate in row.items():
        normalized = _column_key(key)
        if "来源说明" not in normalized:
            continue
        if any(alias in normalized for alias in normalized_aliases):
            source = _text(candidate)
            if source:
                break
    source_period, announcement_date, source_type = _disclosure_from_source(source)
    return (
        value,
        _normalize_report_period(period) or source_period,
        source_type or disclosure_type,
        announcement_date,
        source or None,
    )


def _disclosure_from_source(source: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse report period, announcement date and type from an iWencai source note."""
    if not source:
        return None, None, None
    dates = [
        _normalize_report_period(value)
        for value in re.findall(r"\d{4}(?:[-年])\d{1,2}(?:[-月])\d{1,2}", source)
    ]
    dates = [value for value in dates if value]
    if "业绩预告" in source:
        disclosure_type = "earnings_forecast"
    elif "业绩快报" in source:
        disclosure_type = "quick_report"
    elif any(token in source for token in ("一季报", "三季报", "半年度报告", "年度报告", "年报", "定期报告")):
        disclosure_type = "financial_statement"
    else:
        disclosure_type = None
    if len(dates) >= 2 and "公告" in source:
        # Real source notes use: "来源于<公告日>公告的<报告期>的业绩预告".
        return dates[1], dates[0], disclosure_type
    return (dates[-1] if dates else None), None, disclosure_type


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


def _dated_holder_count(
    rows: Iterable[Mapping[str, Any]], aliases: Iterable[str],
) -> tuple[Optional[int], Optional[str]]:
    normalized_aliases = [_column_key(alias) for alias in aliases]
    values: list[tuple[int, str]] = []
    for row in rows:
        for key, raw in row.items():
            normalized = _column_key(key)
            if not any(alias in normalized for alias in normalized_aliases):
                continue
            match = re.search(r"\[(\d{8})\]", str(key))
            number = _number(raw)
            if match and number is not None and number >= 0 and float(number).is_integer():
                values.append((int(number), match.group(1)))
    if not values:
        return None, None
    latest_period = max(item[1] for item in values)
    latest_values = {item[0] for item in values if item[1] == latest_period}
    return (latest_values.pop(), latest_period) if len(latest_values) == 1 else (None, None)


def _top10_holder_change_summary(rows: Iterable[Mapping[str, Any]]) -> Optional[str]:
    """Summarize top-10 changes only when counts or all ten current ranks are proven."""
    rows = list(rows)
    count_specs = (
        ("新进", ("新进股东个数", "新增股东个数")),
        ("增持", ("增持股东个数",)),
        ("减持", ("减持股东个数",)),
        ("不变", ("不变股东个数",)),
    )
    direct_counts: list[tuple[str, int]] = []
    periods = []
    for label, aliases in count_specs:
        count, period = _dated_holder_count(rows, aliases)
        if count is not None:
            direct_counts.append((label, count))
            if period:
                periods.append(period)
    announcement_date = max(
        (_text(_pick(row, ("公告日期",))) for row in rows),
        default="",
    )
    if {name for name, _count in direct_counts} >= {"新进", "减持"}:
        period = max(periods, default="")
        prefix = announcement_date
        if period:
            prefix = f"{prefix + '（' if prefix else ''}报告期{period}{'）' if prefix else ''}"
        return f"{prefix + '：' if prefix else ''}{'，'.join(f'{name}{count}名' for name, count in direct_counts)}"

    # Detail fallback is valid only if the response contains each current rank
    # 1..10.  Rows such as ``新出`` have no current rank and must not be mixed
    # into the current top-ten population.
    current: dict[int, str] = {}
    for row in rows:
        rank = _number(_pick(row, ("排名", "当期排名")))
        change_type = _text(_pick(row, ("持股变动类型", "变动类型")))
        if rank is None or not float(rank).is_integer() or not 1 <= int(rank) <= 10:
            continue
        current[int(rank)] = change_type
    if set(current) != set(range(1, 11)) or any(not value for value in current.values()):
        return None
    type_counts: Dict[str, int] = {}
    for change_type in current.values():
        type_counts[change_type] = type_counts.get(change_type, 0) + 1
    ordered = [name for name, _aliases in count_specs if name in type_counts]
    ordered.extend(name for name in type_counts if name not in ordered)
    parts = [f"{name}{type_counts[name]}名" for name in ordered]
    return f"{announcement_date + '：' if announcement_date else ''}{'，'.join(parts)}"


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
        report_date = _normalize_report_period(
            _pick(row, ("最新报告期", "报告期", "报告日期")) or _dated_metric_date(
                row, ("净资产收益率", "毛利率", "经营活动产生的现金流量净额")
            )
        )
        revenue_raw, revenue_period, revenue_type, revenue_ann, revenue_source = _pick_metric_with_date(
            row, ("营业收入", "营业总收入")
        )
        profit_raw, profit_period, profit_type, profit_ann, profit_source = _pick_metric_with_date(
            row, ("归母净利润", "归属于母公司股东的净利润", "净利润")
        )
        cash_raw, cash_period, cash_type, cash_ann, cash_source = _pick_metric_with_date(row, (
            "经营活动产生的现金流量净额", "经营活动现金流量净额", "经营现金流",
        ))
        roe_period = _normalize_report_period(_dated_metric_date(row, ("净资产收益率",))) or report_date
        revenue_yoy_period = _normalize_report_period(_dated_metric_date(
            row, ("营业收入同比增长率", "营收同比增长率", "营业收入同比"),
        ))
        profit_yoy_period = _normalize_report_period(_dated_metric_date(
            row, ("归母净利润同比增长率", "净利润同比增长率", "归母净利润同比"),
        ))

        field_values = {
            "revenue": (
                _number(revenue_raw)
                if revenue_type != "earnings_forecast" and revenue_period else None
            ),
            "net_profit_parent": (
                _number(profit_raw)
                if profit_type != "earnings_forecast" and profit_period else None
            ),
            "operating_cash_flow": (
                _number(cash_raw)
                if cash_type != "earnings_forecast" and cash_period else None
            ),
            "roe": roe,
        }
        field_periods = {
            "revenue": revenue_period,
            "net_profit_parent": profit_period,
            "operating_cash_flow": cash_period,
            "roe": roe_period,
        }
        field_report_types = {
            "revenue": revenue_type,
            "net_profit_parent": profit_type,
            "operating_cash_flow": cash_type,
            "roe": None,
        }
        field_announcement_dates = {
            "revenue": revenue_ann,
            "net_profit_parent": profit_ann,
            "operating_cash_flow": cash_ann,
            "roe": None,
        }
        field_sources = {
            "revenue": revenue_source,
            "net_profit_parent": profit_source,
            "operating_cash_flow": cash_source,
            "roe": None,
        }
        present_fields = {key for key, value in field_values.items() if value is not None}
        financial_report: Dict[str, Any] = {
            "report_date": report_date,
            **{key: value for key, value in field_values.items() if key in present_fields},
            "field_periods": {
                key: value for key, value in field_periods.items()
                if key in present_fields and value is not None
            },
            "field_report_types": {
                key: field_report_types[key] for key in present_fields
            },
            "field_announcement_dates": {
                key: value for key, value in field_announcement_dates.items()
                if key in present_fields and value is not None
            },
            "field_sources": {
                key: value for key, value in field_sources.items()
                if key in present_fields and value is not None
            },
        }

        supplemental_reports: List[Dict[str, Any]] = []
        forecast_values = {
            "revenue": _number(revenue_raw) if revenue_type == "earnings_forecast" else None,
            "net_profit_parent": _number(profit_raw) if profit_type == "earnings_forecast" else None,
            "revenue_yoy": revenue_yoy if revenue_type == "earnings_forecast" else None,
            "net_profit_yoy": profit_yoy if profit_type == "earnings_forecast" else None,
        }
        forecast_fields = {key for key, value in forecast_values.items() if value is not None}
        forecast_period = revenue_period if revenue_type == "earnings_forecast" else None
        forecast_period = forecast_period or (
            profit_period if profit_type == "earnings_forecast" else None
        )
        forecast_ann = revenue_ann if revenue_type == "earnings_forecast" else None
        forecast_ann = forecast_ann or (profit_ann if profit_type == "earnings_forecast" else None)
        forecast_source = revenue_source if revenue_type == "earnings_forecast" else None
        forecast_source = forecast_source or (
            profit_source if profit_type == "earnings_forecast" else None
        )
        if forecast_fields:
            supplemental_reports.append({
                "report_date": forecast_period,
                "announcement_date": forecast_ann,
                "available_at": forecast_ann,
                "report_type": "earnings_forecast",
                "document_type": "earnings_forecast",
                "data_basis": (
                    "midpoint_of_forecast_range"
                    if forecast_source and "中值" in forecast_source else None
                ),
                **{key: value for key, value in forecast_values.items() if key in forecast_fields},
                "field_periods": {key: forecast_period for key in forecast_fields if forecast_period},
                "field_report_types": {key: "earnings_forecast" for key in forecast_fields},
                "field_announcement_dates": {
                    key: forecast_ann for key in forecast_fields if forecast_ann
                },
                "field_sources": {
                    key: forecast_source for key in forecast_fields if forecast_source
                },
                "period_consistency": "consistent" if forecast_period else "period_unverified",
            })

        errors = []
        missing_reasons: Dict[str, str] = {}
        for field, raw_value, period, disclosure_type in (
            ("revenue", revenue_raw, revenue_period, revenue_type),
            ("net_profit_parent", profit_raw, profit_period, profit_type),
            ("operating_cash_flow", cash_raw, cash_period, cash_type),
        ):
            if (
                _number(raw_value) is not None
                and disclosure_type != "earnings_forecast"
                and not period
            ):
                missing_reasons[f"earnings.{field}"] = "report_period_unattributed"
        # When the broad "latest" query resolves income metrics to a forecast,
        # explicitly fetch the formal statement for the independently dated
        # ROE/cash-flow period.  If this fetch fails, forecast values remain
        # supplemental and are never backfilled into that statement period.
        if forecast_fields and report_date:
            report_labels = {
                "03-31": "一季度报告",
                "06-30": "半年度报告",
                "09-30": "三季度报告",
                "12-31": "年度报告",
            }
            report_label = report_labels.get(report_date[5:])
            if report_label:
                formal_query = (
                    f"{stock_code} {report_date[:4]}年{report_label} 营业收入 营业收入同比增长率 "
                    "归母净利润 归母净利润同比增长率 净资产收益率 毛利率 "
                    "经营活动现金流量净额 公告日期"
                )
                try:
                    formal_row = self._stock_row(
                        self.query(formal_query, skill_id="hithink-finance-query", limit=3),
                        stock_code,
                    )
                    if formal_row:
                        formal_metrics = {
                            "revenue": _pick_metric_with_date(
                                formal_row, ("营业收入", "营业总收入"),
                                report_type="financial_statement",
                            ),
                            "net_profit_parent": _pick_metric_with_date(
                                formal_row,
                                ("归母净利润", "归属于母公司股东的净利润", "净利润"),
                                report_type="financial_statement",
                            ),
                            "operating_cash_flow": _pick_metric_with_date(
                                formal_row,
                                ("经营活动产生的现金流量净额", "经营活动现金流量净额", "经营现金流"),
                                report_type="financial_statement",
                            ),
                            "roe": (
                                _pick(formal_row, ("净资产收益率", "roe")),
                                _normalize_report_period(_dated_metric_date(formal_row, ("净资产收益率",))),
                                "financial_statement", None, None,
                            ),
                        }
                        formal_values = {
                            key: _number(metric[0]) for key, metric in formal_metrics.items()
                            if _number(metric[0]) is not None
                        }
                        formal_periods = {
                            key: metric[1] or report_date for key, metric in formal_metrics.items()
                            if key in formal_values
                        }
                        announcement_date = _normalize_report_period(
                            _pick(formal_row, ("公告日期",))
                        )
                        financial_report = {
                            "report_date": report_date,
                            "announcement_date": announcement_date,
                            "available_at": announcement_date,
                            "report_type": "financial_statement",
                            "document_type": report_label,
                            **formal_values,
                            "field_periods": formal_periods,
                            "field_report_types": {
                                key: "financial_statement" for key in formal_values
                            },
                            "field_announcement_dates": {
                                key: announcement_date for key in formal_values if announcement_date
                            },
                            "field_sources": {
                                key: f"iwencai:{report_date[:4]}年{report_label}"
                                for key in formal_values
                            },
                            "period_consistency": "consistent",
                        }
                        revenue_yoy = _number(_pick(formal_row, (
                            "营业收入同比增长率", "营收同比增长率", "营业收入同比",
                        )))
                        profit_yoy = _number(_pick(formal_row, (
                            "归母净利润同比增长率", "净利润同比增长率", "归母净利润同比",
                        )))
                        roe = _number(_pick(formal_row, ("净资产收益率", "roe")))
                        gross_margin = _number(_pick(formal_row, ("毛利率", "销售毛利率")))
                    else:
                        missing_reasons["earnings.formal_revenue_profit"] = "formal_report_query_empty"
                except Exception as exc:
                    errors.append(f"earnings_formal:iwencai:{type(exc).__name__}")
                    missing_reasons["earnings.formal_revenue_profit"] = "formal_report_fetch_failed"

        growth = {
            "revenue_yoy": (
                revenue_yoy
                if financial_report.get("revenue") is not None or revenue_yoy_period else None
            ),
            "net_profit_yoy": (
                profit_yoy
                if financial_report.get("net_profit_parent") is not None or profit_yoy_period else None
            ),
            "roe": roe,
            "gross_margin": gross_margin,
        }
        institution = {
            "shareholder_count_change": _number(_pick(row, (
                "总户数较上期变动", "总户数较上期增长率", "股东户数变化", "股东户数增减",
            ))),
        }
        earnings = (
            {
                "financial_report": financial_report,
                **({"supplemental_financial_reports": supplemental_reports} if supplemental_reports else {}),
            }
            if any(
                financial_report.get(key) is not None
                for key in ("report_date", "revenue", "net_profit_parent", "operating_cash_flow", "roe")
            ) else ({"supplemental_financial_reports": supplemental_reports} if supplemental_reports else {})
        )
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
        top10_query = (
            f"{stock_code} 最新十大股东持股变动 新进股东个数 减持股东个数"
        )
        try:
            top10_rows = self._stock_rows(
                self.query(top10_query, skill_id="hithink-finance-query", limit=30), stock_code
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
