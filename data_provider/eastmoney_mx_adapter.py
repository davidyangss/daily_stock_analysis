# -*- coding: utf-8 -*-
"""Fail-open adapter for the official Eastmoney Miaoxiang Skills API."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, Mapping, Optional

from .realtime_types import RealtimeSource, UnifiedRealtimeQuote

_API_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
_MULTIPLIERS = {
    "万亿": 1_000_000_000_000,
    "亿": 100_000_000,
    "万": 10_000,
    "千": 1_000,
}


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"-", "--", "none", "null", "nan"}:
        return None
    multiplier = 1
    for suffix, factor in _MULTIPLIERS.items():
        if suffix in text:
            multiplier = factor
            break
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(match.group()) * multiplier if match else None


def _code_matches(raw: Any, stock_code: str) -> bool:
    returned = re.sub(r"\D", "", str(raw or "").split(".", 1)[0])
    expected = re.sub(r"\D", "", stock_code)
    return bool(returned) and returned.lstrip("0") == expected.lstrip("0")


class EastmoneyMxAdapter:
    """Normalize selected read-only Miaoxiang capabilities for DSA providers."""

    def __init__(self, api_key: str, timeout: float = 8.0):
        self.api_key = (api_key or "").strip()
        self.timeout = max(0.1, float(timeout))

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def query(self, query: str) -> Dict[str, Any]:
        if not self.available:
            raise RuntimeError("MX_APIKEY is not configured")
        request = urllib.request.Request(
            _API_URL,
            data=json.dumps({"toolQuery": query}, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "apikey": self.api_key},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Eastmoney MX request failed: {type(exc).__name__}") from exc
        if not isinstance(result, dict) or result.get("status") != 0:
            message = result.get("message", "invalid response") if isinstance(result, dict) else "non-object response"
            raise RuntimeError(f"Eastmoney MX response invalid: {message}")
        return result

    @staticmethod
    def _tables(result: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        data: Any = result
        for key in ("data", "data", "searchDataResultDTO", "dataTableDTOList"):
            data = data.get(key, {}) if isinstance(data, Mapping) else {}
        return data if isinstance(data, list) else []

    @staticmethod
    def _current_values(result: Mapping[str, Any], stock_code: str) -> tuple[Dict[str, Any], str, str]:
        values: Dict[str, Any] = {}
        name = ""
        timestamp = ""
        for block in EastmoneyMxAdapter._tables(result):
            if block.get("dataTypeEnum") != "HQ" or not _code_matches(block.get("code"), stock_code):
                continue
            table = block.get("table") or {}
            name_map = block.get("nameMap") or {}
            if not isinstance(table, Mapping) or not isinstance(name_map, Mapping):
                continue
            heads = table.get("headName") or []
            if heads and not timestamp:
                timestamp = str(heads[0])
            entity_name = str(block.get("entityName") or "")
            if entity_name and not name:
                name = re.sub(r"\s*\([^)]*\)\s*$", "", entity_name)
            for key, label in name_map.items():
                raw_values = table.get(key)
                if isinstance(raw_values, list) and raw_values:
                    values[str(label)] = raw_values[0]
        return values, name, timestamp

    @staticmethod
    def _pick(values: Mapping[str, Any], *aliases: str) -> Any:
        normalized = {re.sub(r"[\s()（）]", "", key).lower(): value for key, value in values.items()}
        for alias in aliases:
            wanted = re.sub(r"[\s()（）]", "", alias).lower()
            for key, value in normalized.items():
                if wanted == key or wanted in key:
                    return value
        return None

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        query = (
            f"{stock_code} 当前最新价 涨跌幅 涨跌额 成交量 成交额 换手率 量比 振幅 "
            "开盘价 最高价 最低价 昨收价 市盈率TTM 市净率 总市值 流通市值"
        )
        values, name, timestamp = self._current_values(self.query(query), stock_code)
        price = _number(self._pick(values, "最新价"))
        if price is None or price <= 0:
            return None
        volume = _number(self._pick(values, "成交量"))
        return UnifiedRealtimeQuote(
            code=stock_code,
            name=name,
            source=RealtimeSource.EASTMONEY_MX,
            provider_timestamp=timestamp or None,
            price=price,
            change_pct=_number(self._pick(values, "涨跌幅")),
            change_amount=_number(self._pick(values, "涨跌额")),
            volume=int(volume) if volume is not None else None,
            amount=_number(self._pick(values, "成交额")),
            volume_ratio=_number(self._pick(values, "量比")),
            turnover_rate=_number(self._pick(values, "换手率")),
            amplitude=_number(self._pick(values, "振幅")),
            open_price=_number(self._pick(values, "开盘价")),
            high=_number(self._pick(values, "最高价")),
            low=_number(self._pick(values, "最低价")),
            pre_close=_number(self._pick(values, "昨收价", "昨收")),
            pe_ratio=_number(self._pick(values, "市盈率PE(TTM)", "市盈率TTM", "市盈率")),
            pb_ratio=_number(self._pick(values, "市净率PB", "市净率")),
            total_mv=_number(self._pick(values, "总市值")),
            circ_mv=_number(self._pick(values, "流通市值")),
        )

    def get_capital_flow(self, stock_code: str) -> Dict[str, Any]:
        result = self.query(f"{stock_code} 当前主力净流入 近5日主力净流入 近10日主力净流入")
        values: Dict[str, Any] = {}
        daily_values = []
        for block in self._tables(result):
            if not _code_matches(block.get("code"), stock_code):
                continue
            table = block.get("table") or {}
            names = block.get("nameMap") or {}
            if not isinstance(table, Mapping) or not isinstance(names, Mapping):
                continue
            for key, label in names.items():
                rows = table.get(key)
                if isinstance(rows, list) and rows:
                    values[str(label)] = rows[0]
                    normalized_label = re.sub(r"\s", "", str(label))
                    if (
                        block.get("dataTypeEnum") == "DATA_BROWSER"
                        and "主力净流入" in normalized_label
                        and "5日" not in normalized_label
                        and "10日" not in normalized_label
                    ):
                        daily_values = [number for value in rows if (number := _number(value)) is not None]
        five_day = _number(self._pick(values, "近5日主力净流入", "5日主力净流入"))
        ten_day = _number(self._pick(values, "近10日主力净流入", "10日主力净流入"))
        if five_day is None and len(daily_values) >= 5:
            five_day = sum(daily_values[:5])
        if ten_day is None and len(daily_values) >= 10:
            ten_day = sum(daily_values[:10])
        main_value = self._pick(values, "当日主力净流入", "当前主力净流入")
        if main_value is None:
            main_value = next(
                (
                    value for label, value in values.items()
                    if "主力净流入" in re.sub(r"\s", "", label)
                    and "5日" not in label and "10日" not in label
                ),
                None,
            )
        flow = {
            "main_net_inflow": _number(main_value),
            "inflow_5d": five_day,
            "inflow_10d": ten_day,
        }
        flow = {key: value for key, value in flow.items() if value is not None}
        return {
            "status": "partial" if flow else "not_supported",
            "stock_flow": flow,
            "sector_rankings": {"top": [], "bottom": []},
            "source_chain": [{"provider": "eastmoney_mx", "result": "partial", "duration_ms": 0}] if flow else [],
            "errors": [],
        }
