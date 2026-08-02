from datetime import date, datetime

from src.trader_analysis.reporting import reports_from_state
from src.trader_analysis.schemas.evidence import EvidenceEnvelope, EvidenceLedger, EvidenceStatus


def _envelope(capability: str, payload: dict, provider: str) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        evidence_id=capability,
        run_id="run-1",
        capability=capability,
        symbol="600519",
        trade_date=date(2026, 7, 31),
        fetched_at=datetime(2026, 8, 1, 10, 0),
        status=EvidenceStatus.OK,
        provider=provider,
        payload=payload,
    )


def test_news_and_sentiment_reports_append_cross_checkable_evidence() -> None:
    ledger = EvidenceLedger(
        run_id="run-1", symbol="600519", trade_date=date(2026, 7, 31),
        created_at=datetime(2026, 8, 1, 10, 0),
    )
    ledger.add(_envelope("news", {"items": [{
        "title": "业绩预告", "snippet": "净利润增长", "source": "交易所",
        "published_date": "2026-07-31", "fetched_at": "2026-08-01T10:00:00",
        "url": "https://example.com/news",
    }]}, "Anspire"))
    ledger.add(_envelope("sentiment", {"social_items": [{
        "title": "社区讨论", "snippet": "估值观点分歧", "source": "xueqiu.com",
        "published_date": None, "fetched_at": "2026-08-01T10:00:00",
        "url": "https://xueqiu.com/example",
    }]}, "SearXNG"))

    reports = reports_from_state(
        {"news_report": "新闻结论", "sentiment_report": "情绪结论"}, ledger=ledger,
    )
    by_kind = {report.kind: report.content for report in reports}

    assert "证据摘要与来源" in by_kind["news"]
    assert "交易所" in by_kind["news"]
    assert "2026-07-31" in by_kind["news"]
    assert "https://example.com/news" in by_kind["news"]
    assert "xueqiu.com" in by_kind["sentiment"]
    assert "未提供" in by_kind["sentiment"]
    assert "https://xueqiu.com/example" in by_kind["sentiment"]


def test_report_prefers_browser_excerpt_and_labels_evidence_type() -> None:
    ledger = EvidenceLedger(
        run_id="run-1", symbol="600519", trade_date=date(2026, 7, 31),
        created_at=datetime(2026, 8, 1, 10, 0),
    )
    ledger.add(_envelope("news", {"items": [{
        "title": "公告解读", "search_snippet": "搜索摘要", "content_excerpt": "浏览器读取的正文",
        "content_kind": "browser_excerpt", "content_fetch_status": "ok",
        "content_fetched_at": "2026-08-01T10:05:00",
        "source": "sse.com.cn", "url": "https://sse.com.cn/example",
    }]}, "Anspire"))

    report = reports_from_state({"news_report": "新闻结论"}, ledger=ledger)[0]

    assert "浏览器正文摘录" in report.content
    assert "浏览器读取的正文" in report.content
    assert "公告解读：搜索摘要" not in report.content
    assert "2026-08-01T10:05:00" in report.content
