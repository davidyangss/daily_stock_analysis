from datetime import date, datetime

from src.trader_analysis.evidence.renderer import render_quality_summary
from src.trader_analysis.reporting import reports_from_state, render_evidence_manifest
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


def test_complete_evidence_manifest_distinguishes_loaded_and_consumed_data() -> None:
    ledger = EvidenceLedger(
        run_id="run-1", symbol="600519", trade_date=date(2026, 7, 31),
        created_at=datetime(2026, 8, 1, 10, 0),
    )
    ledger.add(_envelope("market_daily_bars", {
        "adjustment": "qfq",
        "rows": [{
            "trade_date": "2026-07-31", "open": 1400, "high": 1420,
            "low": 1390, "close": 1410, "volume_shares": 0,
            "amount_cny": 0, "pct_change": 1.2,
        }],
    }, "TushareFetcher"))
    ledger.add(_envelope("news", {"items": [{
        "title": "公司公告", "publisher": "上交所", "search_provider": "Anspire",
        "published_date": "2026-07-31", "fetched_at": "2026-08-01T10:00:00",
    }]}, "Anspire"))

    content = render_evidence_manifest(
        ledger, consumed_capabilities={"market_daily_bars"},
    )

    assert "预检已加载" in content
    assert "TushareFetcher" in content
    assert "| market_daily_bars |" in content and "| 是 |" in content
    assert "| news |" in content and "| 否 |" in content
    assert "| 2026-07-31 | 1400 | 1420 | 1390 | 1410 | 0 | 0 | 1.2 |" in content
    assert '"publisher": "上交所"' in content
    assert '"search_provider": "Anspire"' in content


def test_market_report_discloses_unadjusted_historical_indicator_basis() -> None:
    ledger = EvidenceLedger(
        run_id="run-1", symbol="603986", trade_date=date(2026, 7, 31),
        created_at=datetime(2026, 8, 1, 10, 0),
    )
    ledger.add(_envelope("market_daily_bars", {
        "adjustment": "none",
        "rows": [{"trade_date": "2026-07-31", "close": 378.6}],
    }, "TushareFetcher"))

    reports = reports_from_state({"market_report": "# 市场技术分析\n\n趋势方向保持不变。"}, ledger=ledger)
    market = next(report.content for report in reports if report.kind == "market")

    assert market.startswith("> 数据口径（adjustment=`none`）")
    assert "技术指标基于不复权日线数据计算" in market
    assert "历史指标值可能与前复权行情软件显示存在差异" in market
    assert "RSI(14) 采用 Wilder EMA/SMMA 递推平滑（alpha=1/14）" in market
    assert "不是最近 14 个交易日涨跌的算术滚动均值" in market
    assert "趋势方向保持不变" in market


def test_reports_add_evidence_manifest_even_without_graph_reports() -> None:
    ledger = EvidenceLedger(
        run_id="run-1", symbol="600519", trade_date=date(2026, 7, 31),
        created_at=datetime(2026, 8, 1, 10, 0),
    )
    ledger.add(_envelope("news", {"items": []}, "Anspire"))

    reports = reports_from_state({}, ledger=ledger)

    assert [report.kind for report in reports] == ["data_evidence"]


def test_quality_summary_localizes_status_and_preserves_stable_code() -> None:
    ledger = EvidenceLedger(
        run_id="run-1", symbol="600519", trade_date=date(2026, 7, 31),
        created_at=datetime(2026, 8, 1, 10, 0), overall_status="degraded",
    )

    content = render_quality_summary(ledger)

    assert "总体状态：降级可用（degraded）" in content
