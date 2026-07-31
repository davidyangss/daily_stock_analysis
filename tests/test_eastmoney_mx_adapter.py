# -*- coding: utf-8 -*-
"""Contract tests for the Eastmoney Miaoxiang read-only adapter."""

from unittest.mock import patch

import pytest

from data_provider.eastmoney_mx_adapter import EastmoneyMxAdapter
from data_provider.realtime_types import RealtimeSource


def _result(*tables):
    return {"status": 0, "data": {"data": {"searchDataResultDTO": {"dataTableDTOList": list(tables)}}}}


def test_realtime_quote_uses_current_hq_table_and_normalizes_units() -> None:
    historical = {
        "code": "600519.SH", "dataTypeEnum": "DATA_BROWSER",
        "nameMap": {"close": "收盘价"},
        "table": {"close": ["999元"], "headName": ["2026-07-30"]},
    }
    current = {
        "code": "600519.SH", "entityName": "贵州茅台(600519.SH)", "dataTypeEnum": "HQ",
        "nameMap": {"price": "最新价", "volume": "成交量", "mv": "总市值", "pct": "涨跌幅"},
        "table": {
            "price": ["1350.60"], "volume": ["551.3万"], "mv": ["1.688万亿"],
            "pct": ["-0.82%"], "headName": ["2026-07-31 16:46"],
        },
    }
    adapter = EastmoneyMxAdapter("secret")
    with patch.object(adapter, "query", return_value=_result(historical, current)):
        quote = adapter.get_realtime_quote("600519")

    assert quote is not None
    assert quote.source == RealtimeSource.EASTMONEY_MX
    assert quote.price == 1350.6
    assert quote.volume == 5_513_000
    assert quote.total_mv == 1_688_000_000_000
    assert quote.provider_timestamp == "2026-07-31 16:46"


def test_realtime_quote_rejects_mismatched_security() -> None:
    adapter = EastmoneyMxAdapter("secret")
    table = {
        "code": "000001.SZ", "dataTypeEnum": "HQ",
        "nameMap": {"price": "最新价"}, "table": {"price": ["10"], "headName": ["now"]},
    }
    with patch.object(adapter, "query", return_value=_result(table)):
        assert adapter.get_realtime_quote("600519") is None


def test_capital_flow_normalizes_each_window() -> None:
    adapter = EastmoneyMxAdapter("secret")
    table = {
        "code": "600519.SH", "dataTypeEnum": "DATA_BROWSER",
        "nameMap": {"d": "当日主力净流入", "d5": "近5日主力净流入", "d10": "近10日主力净流入"},
        "table": {"d": ["1.2亿"], "d5": ["3.4亿"], "d10": ["-2.1亿"], "headName": ["2026-07-31"]},
    }
    with patch.object(adapter, "query", return_value=_result(table)):
        result = adapter.get_capital_flow("600519")

    assert result["stock_flow"] == {
        "main_net_inflow": 120_000_000,
        "inflow_5d": 340_000_000,
        "inflow_10d": -210_000_000,
    }
    assert result["source_chain"][0]["provider"] == "eastmoney_mx"


def test_capital_flow_sums_daily_rows_only_for_complete_windows() -> None:
    adapter = EastmoneyMxAdapter("secret")
    current = {
        "code": "600519.SH", "dataTypeEnum": "HQ",
        "nameMap": {"flow": "主力净流入资金"},
        "table": {"flow": ["-2.18亿"], "headName": ["2026-07-31 16:55"]},
    }
    history = {
        "code": "600519.SH", "dataTypeEnum": "DATA_BROWSER",
        "nameMap": {"flow": "主力净流入资金"},
        "table": {
            "flow": ["-2.18亿", "4.349亿", "5.519亿", "5.119亿", "2.512亿", "-1.363亿", "-1871万", "-2.603亿", "-5.792亿"],
            "headName": [str(index) for index in range(9)],
        },
    }
    with patch.object(adapter, "query", return_value=_result(current, history)):
        result = adapter.get_capital_flow("600519")

    assert result["stock_flow"]["main_net_inflow"] == pytest.approx(-218_000_000)
    assert result["stock_flow"]["inflow_5d"] == pytest.approx(1_531_900_000)
    assert "inflow_10d" not in result["stock_flow"]
