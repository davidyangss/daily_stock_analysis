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


def test_market_stats_normalizes_column_oriented_aggregate_table() -> None:
    adapter = EastmoneyMxAdapter("secret")
    table = {
        "dataTypeEnum": "DATA_BROWSER",
        "nameMap": {
            "up": "上涨家数", "down": "下跌家数", "flat": "平盘家数",
            "lu": "涨停家数", "ld": "跌停家数", "amount": "沪深两市成交额(亿元)",
        },
        "table": {
            "up": [3210], "down": [1800], "flat": [120], "lu": [75],
            "ld": [8], "amount": [19200], "headName": ["2026-07-31"],
        },
    }
    with patch.object(adapter, "query", return_value=_result(table)):
        assert adapter.get_market_stats() == {
            "up_count": 3210, "down_count": 1800, "flat_count": 120,
            "limit_up_count": 75, "limit_down_count": 8, "total_amount": 19200.0,
        }


def test_concept_rankings_normalize_column_oriented_rows() -> None:
    adapter = EastmoneyMxAdapter("secret")
    top_table = {
        "dataTypeEnum": "DATA_BROWSER",
        "nameMap": {"name": "概念名称", "pct": "涨跌幅"},
        "table": {
            "name": ["概念A", "概念B"], "pct": ["1.2%", "3.1%"],
            "headName": ["2026-07-31"],
        },
    }
    bottom_table = {
        "dataTypeEnum": "DATA_BROWSER",
        "nameMap": {"name": "概念名称", "pct": "涨跌幅"},
        "table": {
            "name": ["概念C", "概念D"], "pct": ["-0.5%", "-2.4%"],
            "headName": ["2026-07-31"],
        },
    }
    with patch.object(
        adapter,
        "query",
        side_effect=[_result(top_table), _result(bottom_table)],
    ):
        top, bottom = adapter.get_concept_rankings(2)

    assert [row["change_pct"] for row in top] == [3.1, 1.2]
    assert [row["change_pct"] for row in bottom] == [-2.4, -0.5]


def test_sector_rankings_require_explicit_industry_columns() -> None:
    adapter = EastmoneyMxAdapter("secret")
    industry_table = {
        "dataTypeEnum": "DATA_BROWSER",
        "nameMap": {"name": "行业名称", "pct": "涨跌幅"},
        "table": {"name": ["传媒", "银行"], "pct": ["3.1%", "1.2%"]},
    }
    bottom_table = {
        "dataTypeEnum": "DATA_BROWSER",
        "nameMap": {"name": "行业板块名称", "pct": "板块涨跌幅"},
        "table": {"name": ["电子", "煤炭"], "pct": ["-0.5%", "-2.4%"]},
    }
    with patch.object(
        adapter,
        "query",
        side_effect=[_result(industry_table), _result(bottom_table)],
    ):
        top, bottom = adapter.get_sector_rankings(2)

    assert [row["name"] for row in top] == ["传媒", "银行"]
    assert [row["name"] for row in bottom] == ["煤炭", "电子"]


def test_sector_rankings_reject_all_a_share_aggregate() -> None:
    adapter = EastmoneyMxAdapter("secret")
    aggregate = {
        "dataTypeEnum": "DATA_BROWSER",
        "nameMap": {"name": "板块名称", "pct": "成份区间涨跌幅(流通市值加权平均)"},
        "table": {"name": ["全部A股(板块)"], "pct": ["0.22%"]},
    }
    with patch.object(adapter, "query", side_effect=[_result(aggregate), _result(aggregate)]):
        assert adapter.get_sector_rankings(1) is None


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
