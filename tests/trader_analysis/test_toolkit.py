from datetime import date, datetime

from src.trader_analysis.schemas.evidence import EvidenceEnvelope, EvidenceLedger, EvidenceStatus
from src.trader_analysis.toolkit import DsaTradingAgentsToolkit


def test_toolkit_uses_one_canonical_daily_dataset_for_csv_and_indicators() -> None:
    ledger = EvidenceLedger(run_id="r", symbol="600519", trade_date=date(2026, 7, 31), created_at=datetime.now())
    rows = [
        {"trade_date": f"2026-07-{day:02d}", "open": day, "high": day + 1, "low": day - 1, "close": day, "volume": 100}
        for day in range(1, 32)
    ]
    ledger.add(EvidenceEnvelope(
        evidence_id="daily", run_id="r", capability="market_daily_bars", symbol="600519",
        trade_date=date(2026, 7, 31), fetched_at=datetime.now(), status=EvidenceStatus.OK,
        provider="fixture", payload={"rows": rows},
    ))
    toolkit = DsaTradingAgentsToolkit(ledger)
    assert "2026-07-31" in toolkit.get_stock_data("600519", "2026-07-01", "2026-07-31")
    assert "close_10_ema" in toolkit.get_indicators("600519", "close_10_ema", "2026-07-31")


def test_sentiment_prefetch_uses_social_evidence_without_news() -> None:
    ledger = EvidenceLedger(run_id="r", symbol="600519", trade_date=date(2026, 7, 31), created_at=datetime.now())
    ledger.add(EvidenceEnvelope(
        evidence_id="sentiment", run_id="r", capability="sentiment", symbol="600519",
        trade_date=date(2026, 7, 31), fetched_at=datetime(2026, 8, 1, 10, 0),
        status=EvidenceStatus.PARTIAL, provider="SearXNG",
        payload={"social_items": [{"title": "雪球讨论"}]},
    ))

    bundle = DsaTradingAgentsToolkit(ledger).prefetch_sentiment(
        "600519", "2026-07-24", "2026-07-31",
    )

    assert bundle["social_source"] == "SearXNG"
    assert bundle["social_as_of"] == "2026-08-01 10:00:00"
    assert "雪球讨论" in bundle["social"]
    assert "NOT StockTwits" in bundle["stocktwits"]
    assert "title and search-engine snippet" in bundle["stocktwits"]
    assert "no browser or external tools" in bundle["stocktwits"]
    assert "雪球讨论" in bundle["stocktwits"]
    assert "not used" in bundle["news"]
