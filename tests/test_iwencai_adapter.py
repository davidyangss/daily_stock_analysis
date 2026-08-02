# -*- coding: utf-8 -*-
"""Contract tests for normalized iWencai query responses."""

from unittest.mock import patch

from data_provider.iwencai_adapter import IwencaiAdapter
from data_provider.realtime_types import RealtimeSource


def test_stock_name_does_not_require_realtime_price() -> None:
    adapter = IwencaiAdapter("secret")
    payload = {"datas": [{"股票代码": "600519.SH", "股票简称": "贵州茅台"}]}

    with patch.object(adapter, "query", return_value=payload) as query:
        assert adapter.get_stock_name("600519") == "贵州茅台"

    query.assert_called_once_with("600519 股票简称", skill_id="hithink-market-query", limit=1)


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
        "营业收入[20260331]": 53_909_252_220.51,
        "营业收入同比增长率[20260331]": 6.538,
        "归母净利润[20260331]": 27_242_512_886.45,
        "归母净利润同比增长率[20260331]": 1.4714,
        "净资产收益率[20260331]": 10.5687,
        "销售毛利率[20260331]": 89.7592,
        "经营活动产生的现金流量净额[20260331]": 10_000_000,
        "总户数较上期变动[20260731]": -1234,
    }]}
    top10_payload = {"datas": [
        {
            "股票代码": "600519", "公告日期": "20260428",
            "新进股东个数[20260331]": 1, "减持股东个数[20260331]": 1,
        },
    ]}
    with patch.object(adapter, "query", side_effect=[payload, {"datas": []}, top10_payload]):
        result = adapter.get_fundamental_bundle("600519")

    report = result["earnings"]["financial_report"]
    assert report["report_date"] == "2026-03-31"
    assert report["operating_cash_flow"] == 10_000_000
    assert report["field_periods"] == {
        "revenue": "2026-03-31",
        "net_profit_parent": "2026-03-31",
        "operating_cash_flow": "2026-03-31",
        "roe": "2026-03-31",
    }
    assert report["field_report_types"] == {
        "revenue": None,
        "net_profit_parent": None,
        "operating_cash_flow": None,
        "roe": None,
    }
    assert report["field_announcement_dates"] == {}
    assert report["field_sources"] == {}
    assert result["institution"]["shareholder_count_change"] == -1234
    assert result["institution"]["top10_holder_change"] == (
        "20260428（报告期20260331）：新进1名，减持1名"
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
    assert "financial_report" not in result["earnings"]


def test_top10_query_requests_authoritative_counts_with_non_truncating_limit() -> None:
    adapter = IwencaiAdapter("secret")
    queries = []

    def fake_query(query, **_kwargs):
        queries.append(query)
        return {"datas": [{"股票代码": "300170", "营业收入同比增长率": 6.3}]}

    with patch.object(adapter, "query", side_effect=fake_query):
        adapter.get_fundamental_bundle("300170")

    assert queries[-1] == "300170 最新十大股东持股变动 新进股东个数 减持股东个数"


def test_hande_top10_real_response_shape_and_quick_report_absence_are_explicit() -> None:
    adapter = IwencaiAdapter("secret")
    financial = {"datas": [{"股票代码": "300170.SZ", "营业收入同比增长率": 6.393}]}
    quick_without_report = {"datas": [{"股票代码": "300170.SZ", "股票简称": "汉得信息"}]}
    top10 = {"datas": [{
        "股票代码": "300170.SZ", "公告日期": "20260428",
        "新进股东个数[20260331]": 1, "减持股东个数[20260331]": 1,
    }]}

    with patch.object(adapter, "query", side_effect=[financial, quick_without_report, top10]):
        result = adapter.get_fundamental_bundle("300170")

    assert result["institution"]["top10_holder_change"] == (
        "20260428（报告期20260331）：新进1名，减持1名"
    )
    assert result["missing_reasons"] == {
        "earnings.quick_report_summary": "no_matching_quick_report"
    }


def test_giga_device_forecast_provenance_triggers_formal_q1_query_and_separates_reports() -> None:
    adapter = IwencaiAdapter("secret")
    latest = {"datas": [{
        "股票代码": "603986.SH",
        "营业收入": 11_500_000_000,
        "归母净利润": 6_900_000_000,
        "归母净利润同比增长率": 1099.0083,
        "净资产收益率[20260331]": 6.5999,
        "销售毛利率[20260331]": 57.0767,
        "经营活动产生的现金流量净额[20260331]": 1_783_057_278.72,
        "净利润来源说明": (
            "最新净利润来源于2026-07-10公告的2026-06-30的业绩预告，"
            "计算口径是按上限和下限计算中值得出。"
        ),
        "营业收入来源说明": (
            "最新营业收入来源于2026-07-10公告的2026-06-30的业绩预告，"
            "计算口径是按上限和下限计算中值得出。"
        ),
    }]}
    q1 = {"datas": [{
        "股票代码": "603986.SH",
        "营业收入[20260331]": 4_188_075_574.04,
        "营业收入同比增长率[20260331]": 119.3787,
        "归母净利润[20260331]": 1_461_248_353.08,
        "归母净利润同比增长率[20260331]": 522.7881,
        "净资产收益率[20260331]": 6.5999,
        "销售毛利率[20260331]": 57.0767,
        "经营活动产生的现金流量净额[20260331]": 1_783_057_278.72,
        "公告日期[20260331]": "20260430",
        "报告期[20260331]": "2026年一季报",
    }]}
    holders = {"datas": [{
        "股票代码": "603986.SH", "公告日期": "20260430",
        "新进股东个数[20260331]": 3, "减持股东个数[20260331]": 5,
    }]}
    queries = []

    def fake_query(query, **kwargs):
        queries.append((query, kwargs))
        return [latest, q1, {"datas": []}, holders][len(queries) - 1]

    with patch.object(adapter, "query", side_effect=fake_query):
        result = adapter.get_fundamental_bundle("603986")

    assert "603986 2026年一季度报告" in queries[1][0]
    assert queries[3][1]["limit"] == 30
    formal = result["earnings"]["financial_report"]
    assert formal["report_date"] == "2026-03-31"
    assert formal["announcement_date"] == "2026-04-30"
    assert formal["report_type"] == "financial_statement"
    assert formal["revenue"] == 4_188_075_574.04
    assert formal["net_profit_parent"] == 1_461_248_353.08
    assert formal["operating_cash_flow"] == 1_783_057_278.72
    assert formal["period_consistency"] == "consistent"
    assert result["growth"] == {
        "revenue_yoy": 119.3787,
        "net_profit_yoy": 522.7881,
        "roe": 6.5999,
        "gross_margin": 57.0767,
    }

    forecast = result["earnings"]["supplemental_financial_reports"][0]
    assert forecast["report_date"] == "2026-06-30"
    assert forecast["announcement_date"] == "2026-07-10"
    assert forecast["report_type"] == "earnings_forecast"
    assert forecast["data_basis"] == "midpoint_of_forecast_range"
    assert forecast["revenue"] == 11_500_000_000
    assert forecast["net_profit_parent"] == 6_900_000_000
    assert forecast["net_profit_yoy"] == 1099.0083
    assert result["institution"]["top10_holder_change"] == (
        "20260430（报告期20260331）：新进3名，减持5名"
    )
    assert round(formal["net_profit_parent"] / formal["revenue"] * 100, 4) == 34.8907
    assert round(formal["operating_cash_flow"] / formal["net_profit_parent"] * 100, 4) == 122.0229


def test_forecast_values_stay_supplemental_when_formal_report_fetch_fails() -> None:
    adapter = IwencaiAdapter("secret")
    latest = {"datas": [{
        "股票代码": "603986",
        "营业收入": 11_500_000_000,
        "归母净利润": 6_900_000_000,
        "归母净利润同比增长率": 1099.0083,
        "经营活动产生的现金流量净额[20260331]": 1_783_057_278.72,
        "营业收入来源说明": "来源于2026-07-10公告的2026-06-30的业绩预告，按区间中值得出。",
        "净利润来源说明": "来源于2026-07-10公告的2026-06-30的业绩预告，按区间中值得出。",
    }]}
    calls = 0

    def fake_query(_query, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return latest
        if calls == 2:
            raise RuntimeError("formal report unavailable")
        return {"datas": []}

    with patch.object(adapter, "query", side_effect=fake_query):
        result = adapter.get_fundamental_bundle("603986")

    formal = result["earnings"]["financial_report"]
    assert formal["report_date"] == "2026-03-31"
    assert formal["operating_cash_flow"] == 1_783_057_278.72
    assert "revenue" not in formal and "net_profit_parent" not in formal
    forecast = result["earnings"]["supplemental_financial_reports"][0]
    assert forecast["report_date"] == "2026-06-30"
    assert forecast["revenue"] == 11_500_000_000
    assert forecast["net_profit_parent"] == 6_900_000_000
    assert "net_profit_yoy" not in result["growth"]
    assert "earnings_formal:iwencai:RuntimeError" in result["errors"]
    assert result["missing_reasons"]["earnings.formal_revenue_profit"] == (
        "formal_report_fetch_failed"
    )


def test_top10_detail_fallback_requires_all_current_ranks_and_ignores_new_out_rows() -> None:
    adapter = IwencaiAdapter("secret")
    financial = {"datas": [{"股票代码": "603986", "营业收入同比增长率": 1}]}
    current_types = ["不变", "减持", "新进", "减持", "不变", "减持", "新进", "新进", "减持", "减持"]
    complete_rows = [
        {
            "股票代码": "603986", "公告日期": "20260430",
            "排名": rank, "持股变动类型": change_type,
        }
        for rank, change_type in enumerate(current_types, start=1)
    ] + [
        {"股票代码": "603986", "持股变动类型": "新出"}
        for _ in range(3)
    ]

    with patch.object(
        adapter, "query", side_effect=[financial, {"datas": []}, {"datas": complete_rows}],
    ):
        result = adapter.get_fundamental_bundle("603986")

    assert result["institution"]["top10_holder_change"] == (
        "20260430：新进3名，减持5名，不变2名"
    )


def test_top10_truncated_detail_fails_closed_instead_of_publishing_partial_counts() -> None:
    adapter = IwencaiAdapter("secret")
    financial = {"datas": [{"股票代码": "603986", "营业收入同比增长率": 1}]}
    truncated = {"datas": [
        {"股票代码": "603986", "公告日期": "20260430", "排名": rank, "持股变动类型": "减持"}
        for rank in range(1, 8)
    ]}

    with patch.object(adapter, "query", side_effect=[financial, {"datas": []}, truncated]):
        result = adapter.get_fundamental_bundle("603986")

    assert "top10_holder_change" not in result["institution"]
    assert result["missing_reasons"]["institution.top10_holder_change"] == "no_top10_holder_change"
