from datetime import date, datetime
from types import SimpleNamespace

from src.trader_analysis.adapters.context import ContextEvidenceAdapter
from src.trader_analysis.schemas.evidence import EvidenceStatus


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

    def search_community_sentiment(self, symbol, name, max_results):
        self.calls.append(("sentiment", symbol, name, max_results))
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


def fundamental_payload(*, report_date="2026-03-31", status="ok", missing_reasons=None):
    return {
        "status": status,
        "earnings": {
            "status": "ok",
            "data": {"financial_report": {"report_date": report_date, "revenue": 100}},
        },
        "growth": {"status": "ok", "data": {"roe": 10.5}},
        "source_chain": [{"provider": "tushare", "result": status}],
        "errors": [],
        "missing_reasons": missing_reasons or {},
    }


def test_fundamentals_use_latest_report_for_past_analysis_date() -> None:
    manager = FundamentalManager(fundamental_payload())
    adapter = ContextEvidenceAdapter(manager=manager)

    result = adapter.fetch_fundamentals(
        run_id="run-fundamental", symbol="603986",
        trade_date=date(2026, 7, 31), timeout=12,
    )

    assert manager.calls == [("603986", 12)]
    assert result.status == EvidenceStatus.OK
    assert result.provider == "tushare"
    assert result.payload["report_date"] == "2026-03-31"
    assert result.as_of == datetime(2026, 3, 31)
    assert result.issues == []


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
    assert [issue.code for issue in result.issues] == ["fundamentals_partial"]


def test_fundamentals_expire_only_after_one_year() -> None:
    manager = FundamentalManager(fundamental_payload(report_date="2025-07-30"))
    result = ContextEvidenceAdapter(manager=manager).fetch_fundamentals(
        run_id="run-expired", symbol="603986",
        trade_date=date(2026, 7, 31), timeout=12,
    )

    assert result.status == EvidenceStatus.UNAVAILABLE
    assert [issue.code for issue in result.issues] == ["fundamentals_report_expired"]


def test_fundamentals_without_report_date_remain_partial() -> None:
    manager = FundamentalManager(fundamental_payload(report_date=None))
    result = ContextEvidenceAdapter(manager=manager).fetch_fundamentals(
        run_id="run-no-date", symbol="603986",
        trade_date=date(2026, 7, 31), timeout=12,
    )

    assert result.status == EvidenceStatus.PARTIAL
    assert result.payload["report_date"] is None
    assert [issue.code for issue in result.issues] == ["fundamentals_report_date_missing"]


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

    assert service.calls == [("sentiment", "600519", "贵州茅台", 10)]
    assert result.provider == "SearXNG"
    assert result.status == EvidenceStatus.PARTIAL
    assert "news_items" not in result.payload
    assert result.payload["social_items"][0]["source"] == "xueqiu.com"
    assert result.payload["social_items"][0]["fetched_at"] == "2026-08-01T10:00:00"
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
