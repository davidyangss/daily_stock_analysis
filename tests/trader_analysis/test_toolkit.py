from datetime import date, datetime
from io import StringIO

import pandas as pd
import pytest

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


def test_toolkit_uses_dif_double_macd_histogram_and_wilder_rsi() -> None:
    ledger = EvidenceLedger(run_id="r", symbol="600519", trade_date=date(2026, 7, 31), created_at=datetime.now())
    closes = [10, 11, 12, 11, 13, 12, 14, 15, 13, 16, 17, 15, 18, 19, 17, 20, 21, 19, 22, 23, 21, 24, 25, 23, 26]
    rows = [
        {"trade_date": f"2026-07-{day:02d}", "high": close + 1, "low": close - 1, "close": close}
        for day, close in enumerate(closes, start=1)
    ]
    ledger.add(EvidenceEnvelope(
        evidence_id="daily", run_id="r", capability="market_daily_bars", symbol="600519",
        trade_date=date(2026, 7, 31), fetched_at=datetime.now(), status=EvidenceStatus.OK,
        provider="fixture", payload={"rows": rows},
    ))
    toolkit = DsaTradingAgentsToolkit(ledger)

    dif = pd.read_csv(StringIO(toolkit.get_indicators("600519", "macd", "2026-07-31")))
    dea = pd.read_csv(StringIO(toolkit.get_indicators("600519", "macds", "2026-07-31")))
    histogram = pd.read_csv(StringIO(toolkit.get_indicators("600519", "macdh", "2026-07-31")))
    rsi = pd.read_csv(StringIO(toolkit.get_indicators("600519", "rsi", "2026-07-31")))
    atr = pd.read_csv(StringIO(toolkit.get_indicators("600519", "atr", "2026-07-31")))
    boll_upper = pd.read_csv(StringIO(toolkit.get_indicators("600519", "boll_ub", "2026-07-31")))

    assert histogram["macdh"].iloc[-1] == pytest.approx(
        2 * (dif["macd"].iloc[-1] - dea["macds"].iloc[-1])
    )
    assert rsi["rsi"].iloc[-1] == pytest.approx(68.11129488016466)
    frame = pd.DataFrame(rows)
    true_range = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - frame["close"].shift()).abs(),
        (frame["low"] - frame["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    assert atr["atr"].iloc[-1] == pytest.approx(true_range.rolling(14).mean().iloc[-1])
    close = frame["close"]
    expected_boll_upper = close.rolling(20).mean() + 2 * close.rolling(20).std(ddof=0)
    sample_boll_upper = close.rolling(20).mean() + 2 * close.rolling(20).std(ddof=1)
    assert boll_upper["boll_ub"].iloc[-1] == pytest.approx(expected_boll_upper.iloc[-1])
    assert boll_upper["boll_ub"].iloc[-1] != pytest.approx(sample_boll_upper.iloc[-1])


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
    assert "content_kind=browser_excerpt" in bundle["stocktwits"]
    assert "content_kind=search_snippet" in bundle["stocktwits"]
    assert "no browser or external tools" in bundle["stocktwits"]
    assert "雪球讨论" in bundle["stocktwits"]
    assert "not used" in bundle["news"]
