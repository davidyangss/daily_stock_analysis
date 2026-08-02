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
