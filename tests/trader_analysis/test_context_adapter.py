from datetime import date, datetime
from types import SimpleNamespace

import pytest

from src.trader_analysis.adapters.context import ContextEvidenceAdapter
from src.trader_analysis.schemas.evidence import EvidenceStatus


@pytest.fixture(autouse=True)
def _latest_completed_session(monkeypatch):
    monkeypatch.setattr(
        "src.trader_analysis.adapters.context.get_effective_trading_date",
        lambda market, current_time: date(2026, 7, 31),
    )


class SearchService:
    def __init__(self) -> None:
        self.calls = []

    def search_stock_news(self, symbol, name, max_results):
        self.calls.append((symbol, name, max_results))
        return SimpleNamespace(
            success=True,
            provider="Anspire",
            query="贵州茅台 600519 股票 最新消息",
            results=[SimpleNamespace(
                title="公司公告",
                snippet="摘要",
                url="https://example.com/news",
                source="交易所",
                published_date="2026-07-31",
            )],
        )

    def search_community_sentiment(self, symbol, name, max_results, days):
        self.calls.append(("sentiment", symbol, name, max_results, days))
        return SimpleNamespace(
            success=True,
            provider="SearXNG",
            query='site:xueqiu.com "贵州茅台" 600519 讨论 评价',
            results=[SimpleNamespace(
                title="雪球用户讨论",
                snippet="对估值存在分歧",
                url="https://xueqiu.com/example",
                source="xueqiu.com",
                published_date="2026-07-31T09:30:00+08:00",
            )],
        )


class PageReader:
    def __init__(self) -> None:
        self.calls = []

    def enrich_items(self, items, *, run_id):
        self.calls.append((items, run_id))
        return [{**item, "content_excerpt": "正文摘录", "content_kind": "browser_excerpt"} for item in items]


class FundamentalManager:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls = []

    def get_fundamental_context(self, symbol, budget_seconds):
        self.calls.append((symbol, budget_seconds))
        return self.payload


def fundamental_payload(
    *, report_date="2026-03-31", announcement_date="2026-04-30",
    status="ok", missing_reasons=None,
):
    return {
        "status": status,
        "earnings": {
            "status": "ok",
            "data": {"financial_report": {
                "report_date": report_date,
                "announcement_date": announcement_date,
                "revenue": 100,
            }},
        },
        "growth": {"status": "ok", "data": {"roe": 10.5}},
        "source_chain": [{"provider": "tushare", "result": status}],
        "errors": [],
        "missing_reasons": missing_reasons or {},
    }


def test_latest_session_fundamentals_are_runtime_snapshot_with_explicit_times() -> None:
    manager = FundamentalManager(fundamental_payload())
    adapter = ContextEvidenceAdapter(manager=manager)

    result = adapter.fetch_fundamentals(
        run_id="run-fundamental", symbol="603986",
        trade_date=date(2026, 7, 31), timeout=12,
    )

    assert manager.calls == [("603986", 12)]
    assert result.status == EvidenceStatus.PARTIAL
    assert result.provider == "tushare"
    assert result.payload["report_date"] == "2026-03-31"
    assert result.payload["announcement_date"] == "2026-04-30"
    assert result.payload["available_at"] == "2026-04-30"
    assert result.as_of == datetime(2026, 4, 30)
    assert result.payload["point_in_time"]["mode"] == "runtime_latest_session"
    assert [issue.code for issue in result.issues] == ["fundamentals_runtime_snapshot"]


def test_fundamentals_are_partial_only_when_fields_or_report_date_are_missing() -> None:
    manager = FundamentalManager(fundamental_payload(
        status="partial", missing_reasons={"growth.revenue_yoy": "source_field_missing"},
    ))
    result = ContextEvidenceAdapter(manager=manager).fetch_fundamentals(
        run_id="run-partial", symbol="603986",
        trade_date=date(2026, 7, 31), timeout=12,
    )

    assert result.status == EvidenceStatus.PARTIAL
    assert result.missing_fields == ["growth.revenue_yoy"]
    assert [issue.code for issue in result.issues] == [
        "fundamentals_runtime_snapshot", "fundamentals_partial",
    ]


def test_fundamentals_split_mixed_field_periods_before_model_consumption() -> None:
    payload = fundamental_payload()
    payload["earnings"]["data"]["financial_report"] = {
        "report_date": "2026-03-31",
        "announcement_date": "2026-07-15",
        "revenue": 11_500_000_000,
        "net_profit_parent": 6_900_000_000,
        "operating_cash_flow": 1_783_000_000,
        "field_periods": {
            "revenue": "20260630",
            "net_profit_parent": "2026-06-30",
            "operating_cash_flow": "20260331",
        },
        "field_report_types": {
            "revenue": "earnings_forecast",
            "net_profit_parent": "earnings_forecast",
        },
        "field_announcement_dates": {
            "revenue": "2026-07-15",
            "net_profit_parent": "2026-07-15",
            "operating_cash_flow": "2026-04-30",
        },
        "field_sources": {
            "revenue": "H1业绩预告",
            "net_profit_parent": "H1业绩预告",
            "operating_cash_flow": "Q1定期报告",
        },
    }

    result = ContextEvidenceAdapter(manager=FundamentalManager(payload)).fetch_fundamentals(
        run_id="mixed-periods", symbol="603986", trade_date=date(2026, 7, 31), timeout=12,
    )

    earnings = result.payload["earnings"]["data"]
    assert earnings["financial_report"] == {
        "report_date": "2026-03-31",
        "announcement_date": "2026-04-30",
        "available_at": "2026-04-30",
        "field_periods": {"operating_cash_flow": "2026-03-31"},
        "field_announcement_dates": {"operating_cash_flow": "2026-04-30"},
        "field_sources": {"operating_cash_flow": "Q1定期报告"},
        "operating_cash_flow": 1_783_000_000,
        "report_type": "unclassified_period_data",
        "period_consistency": "period_consistent_disclosure_type_unverified",
    }
    assert earnings["supplemental_financial_reports"] == [{
        "report_date": "2026-06-30",
        "announcement_date": "2026-07-15",
        "field_periods": {
            "revenue": "2026-06-30",
            "net_profit_parent": "2026-06-30",
        },
        "revenue": 11_500_000_000,
        "net_profit_parent": 6_900_000_000,
        "field_report_types": {
            "revenue": "earnings_forecast",
            "net_profit_parent": "earnings_forecast",
        },
        "field_announcement_dates": {
            "revenue": "2026-07-15",
            "net_profit_parent": "2026-07-15",
        },
        "field_sources": {
            "revenue": "H1业绩预告",
            "net_profit_parent": "H1业绩预告",
        },
        "available_at": "2026-07-15",
        "report_type": "earnings_forecast",
        "period_consistency": "separated_from_mixed_provider_payload",
    }]


def test_fundamentals_do_not_label_a_single_h1_field_group_as_declared_q1() -> None:
    payload = fundamental_payload()
    payload["earnings"]["data"]["financial_report"] = {
        "report_date": "2026-03-31",
        "announcement_date": "2026-07-15",
        "revenue": 11_500_000_000,
        "net_profit_parent": 6_900_000_000,
        "field_periods": {
            "revenue": "20260630",
            "net_profit_parent": "2026-06-30",
        },
        "field_report_types": {
            "revenue": "earnings_forecast",
            "net_profit_parent": "earnings_forecast",
        },
    }

    result = ContextEvidenceAdapter(manager=FundamentalManager(payload)).fetch_fundamentals(
        run_id="declared-q1-values-h1", symbol="603986", trade_date=date(2026, 7, 31), timeout=12,
    )

    earnings = result.payload["earnings"]["data"]
    assert earnings["financial_report"] == {
        "report_date": "2026-03-31",
        "field_periods": {},
        "report_type": "unclassified_period_data",
        "period_consistency": "declared_period_without_attributed_values",
    }
    assert earnings["supplemental_financial_reports"][0]["report_date"] == "2026-06-30"
    assert earnings["supplemental_financial_reports"][0]["report_type"] == "earnings_forecast"


def test_fundamentals_split_same_period_when_disclosure_types_differ() -> None:
    payload = fundamental_payload()
    payload["earnings"]["data"]["financial_report"] = {
        "report_date": "2026-03-31",
        "revenue": 1_000,
        "operating_cash_flow": 300,
        "field_periods": {
            "revenue": "2026-03-31",
            "operating_cash_flow": "2026-03-31",
        },
        "field_report_types": {
            "revenue": "earnings_forecast",
            "operating_cash_flow": "financial_statement",
        },
    }

    result = ContextEvidenceAdapter(manager=FundamentalManager(payload)).fetch_fundamentals(
        run_id="same-period-mixed-types", symbol="603986",
        trade_date=date(2026, 7, 31), timeout=12,
    )

    earnings = result.payload["earnings"]["data"]
    assert earnings["financial_report"]["operating_cash_flow"] == 300
    assert earnings["financial_report"]["report_type"] == "financial_statement"
    assert "revenue" not in earnings["financial_report"]
    assert earnings["supplemental_financial_reports"] == [{
        "report_date": "2026-03-31",
        "revenue": 1_000,
        "field_periods": {"revenue": "2026-03-31"},
        "field_report_types": {"revenue": "earnings_forecast"},
        "report_type": "earnings_forecast",
        "period_consistency": "separated_from_mixed_provider_payload",
    }]


def test_fundamentals_expire_only_after_one_year() -> None:
    manager = FundamentalManager(fundamental_payload(report_date="2025-07-30"))
    result = ContextEvidenceAdapter(manager=manager).fetch_fundamentals(
        run_id="run-expired", symbol="603986",
        trade_date=date(2026, 7, 31), timeout=12,
    )

    assert result.status == EvidenceStatus.UNAVAILABLE
    assert [issue.code for issue in result.issues] == ["fundamentals_report_expired"]


def test_fundamentals_without_report_date_remain_partial() -> None:
    manager = FundamentalManager(fundamental_payload(report_date=None, announcement_date=None))
    result = ContextEvidenceAdapter(manager=manager).fetch_fundamentals(
        run_id="run-no-date", symbol="603986",
        trade_date=date(2026, 7, 31), timeout=12,
    )

    assert result.status == EvidenceStatus.PARTIAL
    assert result.payload["report_date"] is None
    assert [issue.code for issue in result.issues] == [
        "fundamentals_report_date_missing", "fundamentals_runtime_snapshot",
    ]


def test_historical_fundamentals_require_announcement_date_at_or_before_cutoff() -> None:
    admitted = ContextEvidenceAdapter(
        manager=FundamentalManager(fundamental_payload(announcement_date="2026-04-30")),
    ).fetch_fundamentals(
        run_id="historical-admitted", symbol="603986",
        trade_date=date(2026, 7, 30), timeout=12,
    )
    rejected = ContextEvidenceAdapter(
        manager=FundamentalManager(fundamental_payload(announcement_date="2026-08-01")),
    ).fetch_fundamentals(
        run_id="historical-rejected", symbol="603986",
        trade_date=date(2026, 7, 30), timeout=12,
    )

    assert admitted.status == EvidenceStatus.OK
    assert admitted.payload["point_in_time"]["status"] == "point_in_time"
    assert admitted.payload["announcement_date"] == "2026-04-30"
    assert rejected.status == EvidenceStatus.UNAVAILABLE
    assert rejected.issues[0].code == "historical_fundamentals_not_point_in_time"
    assert rejected.issues[0].severity.value == "warning"
    assert rejected.payload["earnings"]["data"] == {}


def test_historical_fundamentals_prefer_explicit_available_at_for_admission() -> None:
    payload = fundamental_payload(announcement_date="2026-04-30")
    payload["earnings"]["data"]["financial_report"]["available_at"] = "2026-08-01T09:00:00+08:00"

    result = ContextEvidenceAdapter(manager=FundamentalManager(payload)).fetch_fundamentals(
        run_id="historical-available-at", symbol="603986",
        trade_date=date(2026, 7, 30), timeout=12,
    )

    assert result.status == EvidenceStatus.UNAVAILABLE
    removed = result.payload["point_in_time"]["removed_reports"][0]
    assert removed["announcement_date"] == "2026-04-30"
    assert removed["available_at"] == "2026-08-01"
    assert removed["admission_date"] == "2026-08-01"
    assert removed["reason"] == "not_available_at_cutoff"


def test_runtime_fundamentals_keep_announcement_and_available_dates_distinct() -> None:
    payload = fundamental_payload(announcement_date="2026-04-30")
    payload["earnings"]["data"]["financial_report"]["available_at"] = "2026-08-01T09:00:00+08:00"

    result = ContextEvidenceAdapter(manager=FundamentalManager(payload)).fetch_fundamentals(
        run_id="runtime-available-at", symbol="603986",
        trade_date=date(2026, 7, 31), timeout=12,
    )

    assert result.payload["announcement_date"] == "2026-04-30"
    assert result.payload["available_at"] == "2026-08-01"
    assert result.as_of == datetime(2026, 8, 1)


def test_historical_fundamentals_remove_runtime_only_blocks() -> None:
    payload = fundamental_payload()
    payload["valuation"] = {"status": "ok", "data": {"pe_ratio": 20}}
    payload["capital_flow"] = {"status": "ok", "data": {"main_net_inflow": 1_000_000}}

    result = ContextEvidenceAdapter(manager=FundamentalManager(payload)).fetch_fundamentals(
        run_id="historical-runtime-blocks", symbol="603986",
        trade_date=date(2026, 7, 30), timeout=12,
    )

    assert result.payload["valuation"]["data"] == {}
    assert result.payload["capital_flow"]["data"] == {}
    assert set(result.payload["point_in_time"]["removed_blocks"]) >= {"valuation", "capital_flow"}


def test_historical_primary_statement_stays_aligned_with_growth_when_newer_forecast_exists() -> None:
    payload = fundamental_payload()
    payload["earnings"]["data"]["supplemental_financial_reports"] = [{
        "report_date": "2026-06-30",
        "announcement_date": "2026-07-15",
        "report_type": "earnings_forecast",
        "revenue": 250,
    }]

    result = ContextEvidenceAdapter(manager=FundamentalManager(payload)).fetch_fundamentals(
        run_id="historical-period-alignment", symbol="603986",
        trade_date=date(2026, 7, 30), timeout=12,
    )

    earnings = result.payload["earnings"]["data"]
    assert earnings["financial_report"]["report_date"] == "2026-03-31"
    assert earnings["supplemental_financial_reports"][0]["report_date"] == "2026-06-30"
    assert result.payload["growth"]["data"]["roe"] == 10.5


def test_news_for_latest_completed_session_uses_runtime_dsa_provider(monkeypatch) -> None:
    service = SearchService()
    monkeypatch.setattr(
        "src.trader_analysis.adapters.context.get_effective_trading_date",
        lambda market, current_time: date(2026, 7, 31),
    )
    adapter = ContextEvidenceAdapter(
        manager=object(),
        search_service=service,
        now_provider=lambda: datetime(2026, 8, 1, 10, 0),
    )

    result = adapter.fetch_news(
        run_id="run-1", symbol="600519", name="贵州茅台", trade_date=date(2026, 7, 31),
    )

    assert service.calls == [("600519", "贵州茅台", 10)]
    assert result.status == EvidenceStatus.PARTIAL
    assert result.provider == "Anspire"
    assert result.payload["items"][0]["title"] == "公司公告"
    assert result.as_of == datetime(2026, 7, 31)
    assert [issue.code for issue in result.issues] == ["runtime_news_not_point_in_time"]


def test_news_before_latest_completed_session_remains_point_in_time_blocked(monkeypatch) -> None:
    service = SearchService()
    monkeypatch.setattr(
        "src.trader_analysis.adapters.context.get_effective_trading_date",
        lambda market, current_time: date(2026, 7, 31),
    )
    adapter = ContextEvidenceAdapter(
        manager=object(),
        search_service=service,
        now_provider=lambda: datetime(2026, 8, 1, 10, 0),
    )

    result = adapter.fetch_news(
        run_id="run-1", symbol="600519", name="贵州茅台", trade_date=date(2026, 7, 30),
    )

    assert service.calls == []
    assert result.status == EvidenceStatus.UNAVAILABLE
    assert [issue.code for issue in result.issues] == ["historical_news_not_point_in_time"]


def test_sentiment_uses_independent_community_search(monkeypatch) -> None:
    service = SearchService()
    monkeypatch.setattr(
        "src.trader_analysis.adapters.context.get_effective_trading_date",
        lambda market, current_time: date(2026, 7, 31),
    )
    adapter = ContextEvidenceAdapter(
        manager=object(), search_service=service,
        now_provider=lambda: datetime(2026, 8, 1, 10, 0),
    )

    result = adapter.fetch_sentiment(
        run_id="run-1", symbol="600519", name="贵州茅台", trade_date=date(2026, 7, 31),
    )

    assert service.calls == [("sentiment", "600519", "贵州茅台", 10, 7)]
    assert result.provider == "SearXNG"
    assert result.status == EvidenceStatus.PARTIAL
    assert "news_items" not in result.payload
    assert result.payload["social_items"][0]["source"] == "xueqiu.com"
    assert result.payload["social_items"][0]["fetched_at"] == "2026-08-01T10:00:00"
    assert result.as_of == datetime(2026, 7, 31)
    assert [issue.code for issue in result.issues] == ["runtime_sentiment_not_point_in_time"]


def test_news_and_sentiment_use_the_shared_page_reader(monkeypatch) -> None:
    service = SearchService()
    reader = PageReader()
    monkeypatch.setattr(
        "src.trader_analysis.adapters.context.get_effective_trading_date",
        lambda market, current_time: date(2026, 7, 31),
    )
    adapter = ContextEvidenceAdapter(
        manager=object(), search_service=service, page_reader=reader,
        now_provider=lambda: datetime(2026, 8, 1, 10, 0),
    )

    news = adapter.fetch_news(
        run_id="run-news", symbol="600519", name="贵州茅台", trade_date=date(2026, 7, 31),
    )
    sentiment = adapter.fetch_sentiment(
        run_id="run-sentiment", symbol="600519", name="贵州茅台", trade_date=date(2026, 7, 31),
    )

    assert [call[1] for call in reader.calls] == ["run-news", "run-sentiment"]
    assert news.payload["items"][0]["content_excerpt"] == "正文摘录"
    assert sentiment.payload["social_items"][0]["content_excerpt"] == "正文摘录"
