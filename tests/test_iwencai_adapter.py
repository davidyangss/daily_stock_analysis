# -*- coding: utf-8 -*-
"""Contract tests for normalized iWencai query responses."""

from unittest.mock import patch

from data_provider.iwencai_adapter import IwencaiAdapter
from data_provider.realtime_types import RealtimeSource


def test_realtime_quote_normalizes_date_suffixed_columns_and_units() -> None:
    adapter = IwencaiAdapter("secret")
    payload = {
        "datas": [{
            "股票代码": "600519.SH",
            "股票简称": "贵州茅台",
            "最新价[20260731]": "1418.20",
            "涨跌幅[20260731]": "1.25%",
            "成交量[20260731]": "2.5万",
            "成交额[20260731]": "35.6亿",
            "换手率[20260731]": "0.62%",
            "市盈率(ttm)[20260731]": "21.3",
        }]
    }
    with patch.object(adapter, "query", return_value=payload):
        quote = adapter.get_realtime_quote("600519")

    assert quote is not None
    assert quote.source == RealtimeSource.IWENCAI
    assert quote.price == 1418.2
    assert quote.change_pct == 1.25
    assert quote.volume == 25000
    assert quote.amount == 3_560_000_000
    assert quote.pe_ratio == 21.3


def test_capital_flow_maps_each_window_without_cross_window_fallback() -> None:
    adapter = IwencaiAdapter("secret")
    payload = {
        "datas": [{
            "股票代码": "600519",
            "当日主力净流入[20260731]": "1.2亿",
            "近5日主力累计净流入": "3.4亿",
            "近10日主力累计净流入": "-2.1亿",
        }]
    }
    with patch.object(adapter, "query", return_value=payload):
        result = adapter.get_capital_flow("600519")

    assert result["stock_flow"] == {
        "main_net_inflow": 120_000_000,
        "inflow_5d": 340_000_000,
        "inflow_10d": -210_000_000,
    }
    assert result["source_chain"] == [
        {"provider": "iwencai", "result": "partial", "duration_ms": 0}
    ]


def test_capital_flow_maps_real_query2data_date_range_columns() -> None:
    adapter = IwencaiAdapter("secret")
    payload = {
        "datas": [{
            "股票代码": "600519",
            "主力资金流向[20260731]": "1.2亿",
            "主力资金流向[20260727-20260731]": "3.4亿",
            "主力资金流向[20260720-20260731]": "-2.1亿",
        }]
    }
    with patch.object(adapter, "query", return_value=payload):
        result = adapter.get_capital_flow("600519")

    assert result["stock_flow"] == {
        "main_net_inflow": 120_000_000,
        "inflow_5d": 340_000_000,
        "inflow_10d": -210_000_000,
    }


def test_mismatched_stock_code_is_rejected() -> None:
    adapter = IwencaiAdapter("secret")
    with patch.object(adapter, "query", return_value={"datas": [{"股票代码": "000001", "最新价": 10}]}):
        assert adapter.get_realtime_quote("600519") is None


def test_fundamental_bundle_maps_real_dated_financial_columns() -> None:
    adapter = IwencaiAdapter("secret")
    payload = {"datas": [{
        "股票代码": "600519",
        "营业收入": 53_909_252_220.51,
        "营业收入同比增长率": 6.538,
        "归母净利润": 27_242_512_886.45,
        "归母净利润同比增长率": 1.4714,
        "净资产收益率[20260331]": 10.5687,
        "销售毛利率[20260331]": 89.7592,
        "经营活动产生的现金流量净额[20260331]": 10_000_000,
        "总户数较上期变动[20260731]": -1234,
    }]}
    top10_payload = {"datas": [
        {"股票代码": "600519", "公告日期": "20260428", "持股变动类型": "减持", "持股数量变动": -100},
        {"股票代码": "600519", "公告日期": "20260428", "持股变动类型": "新进", "持股比例变动": 0.5},
    ]}
    with patch.object(adapter, "query", side_effect=[payload, {"datas": []}, top10_payload]):
        result = adapter.get_fundamental_bundle("600519")

    report = result["earnings"]["financial_report"]
    assert report["report_date"] == "20260331"
    assert report["operating_cash_flow"] == 10_000_000
    assert result["institution"]["shareholder_count_change"] == -1234
    assert result["institution"]["top10_holder_change"] == (
        "20260428：减持1名，新进1名，已披露持股数量变动合计-100股，"
        "已披露持股比例变动合计0.5个百分点"
    )


def test_fundamental_bundle_maps_proven_quick_report_without_mislabeling_regular_report() -> None:
    adapter = IwencaiAdapter("secret")
    financial = {"datas": [{"股票代码": "300170", "营业收入同比增长率": 6.3}]}
    quick = {"datas": [{
        "股票代码": "300170",
        "业绩快报公告日期": "20260227",
        "业绩快报营业收入": 3_000_000_000,
        "业绩快报归母净利润": 200_000_000,
        "营业收入来源说明": "数据来源于2025年度业绩快报",
    }]}
    with patch.object(adapter, "query", side_effect=[financial, quick, {"datas": []}]):
        result = adapter.get_fundamental_bundle("300170")

    assert result["earnings"]["quick_report_summary"] == (
        "20260227：营业收入3,000,000,000元，归母净利润200,000,000元"
    )


def test_top10_query_stays_narrow_to_preserve_change_detail_semantics() -> None:
    adapter = IwencaiAdapter("secret")
    queries = []

    def fake_query(query, **_kwargs):
        queries.append(query)
        return {"datas": [{"股票代码": "300170", "营业收入同比增长率": 6.3}]}

    with patch.object(adapter, "query", side_effect=fake_query):
        adapter.get_fundamental_bundle("300170")

    assert queries[-1] == "300170 前十大股东持股数量变动"


def test_hande_top10_real_response_shape_and_quick_report_absence_are_explicit() -> None:
    adapter = IwencaiAdapter("secret")
    financial = {"datas": [{"股票代码": "300170.SZ", "营业收入同比增长率": 6.393}]}
    quick_without_report = {"datas": [{"股票代码": "300170.SZ", "股票简称": "汉得信息"}]}
    top10 = {"datas": [
        {"股票代码": "300170.SZ", "公告日期": "20260428", "持股数量变动": -12_246_371, "持股变动类型": "减持"},
        {"股票代码": "300170.SZ", "公告日期": "20260428", "持股变动类型": "新进"},
        {"股票代码": "300170.SZ", "持股数量变动": -5_422_300, "持股变动类型": "新出"},
        {"股票代码": "300170.SZ", "公告日期": "20260428", "持股数量变动": 0, "持股变动类型": "不变"},
    ]}

    with patch.object(adapter, "query", side_effect=[financial, quick_without_report, top10]):
        result = adapter.get_fundamental_bundle("300170")

    assert result["institution"]["top10_holder_change"] == (
        "20260428：减持1名，新进1名，新出1名，不变1名，"
        "已披露持股数量变动合计-17,668,671股"
    )
    assert result["missing_reasons"] == {
        "earnings.quick_report_summary": "no_matching_quick_report"
    }
