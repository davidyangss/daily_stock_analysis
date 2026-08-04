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
        provider="fixture", payload={"adjustment": "none", "rows": rows},
    ))
    toolkit = DsaTradingAgentsToolkit(ledger)
    daily = pd.read_csv(StringIO(toolkit.get_stock_data("600519", "2026-07-01", "2026-07-31")))
    ema = pd.read_csv(StringIO(toolkit.get_indicators("600519", "close_10_ema", "2026-07-31")))

    assert str(daily["trade_date"].iloc[-1]) == "2026-07-31"
    assert daily["adjustment"].unique().tolist() == ["none"]
    assert "close_10_ema" in ema
    assert ema["adjustment"].unique().tolist() == ["none"]


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
    indicator_tool = next(tool for tool in toolkit.market_tools if tool.name == "get_indicators")
    assert "RSI(14) 使用 Wilder EMA/SMMA 递推平滑" in indicator_tool.description
    assert "非 14 日算术滚动均值" in indicator_tool.description
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


def test_toolkit_never_computes_indicators_across_unadjusted_break() -> None:
    ledger = EvidenceLedger(
        run_id="r", symbol="002595", trade_date=date(2026, 7, 31), created_at=datetime.now(),
    )
    before = [
        {"trade_date": f"2025-{month:02d}-{day:02d}", "close": 80 + day, "high": 81 + day, "low": 79 + day}
        for month in range(1, 6) for day in range(1, 29)
    ]
    after_dates = pd.bdate_range("2026-05-11", periods=60)
    after = [
        {"trade_date": value.date().isoformat(), "close": 50 + index / 10, "high": 51 + index / 10, "low": 49 + index / 10}
        for index, value in enumerate(after_dates)
    ]
    ledger.add(EvidenceEnvelope(
        evidence_id="daily", run_id="r", capability="market_daily_bars", symbol="002595",
        trade_date=date(2026, 7, 31), fetched_at=datetime.now(), status=EvidenceStatus.PARTIAL,
        provider="fixture", payload={
            "adjustment": "none",
            "rows": before + after,
            "corporate_action_breaks": [{"trade_date": "2026-05-11"}],
            "indicator_start_date": "2026-05-11",
        },
    ))
    toolkit = DsaTradingAgentsToolkit(ledger)

    assert "insufficient bars" in toolkit.get_indicators(
        "002595", "close_200_sma", "2026-07-31",
    )
    macd = pd.read_csv(StringIO(toolkit.get_indicators("002595", "macd", "2026-07-31")))
    assert macd["indicator_start_date"].unique().tolist() == ["2026-05-11"]
    assert macd["trade_date"].min() >= "2026-05-11"


def test_sentiment_prefetch_preserves_domestic_news_and_community_sources() -> None:
    trace = []
    ledger = EvidenceLedger(run_id="r", symbol="600519", trade_date=date(2026, 7, 31), created_at=datetime.now())
    ledger.add(EvidenceEnvelope(
        evidence_id="sentiment", run_id="r", capability="sentiment", symbol="600519",
        trade_date=date(2026, 7, 31), fetched_at=datetime(2026, 8, 1, 10, 0),
        status=EvidenceStatus.PARTIAL, provider="SearXNG",
        payload={"social_items": [{"title": "雪球讨论"}]},
    ))
    ledger.add(EvidenceEnvelope(
        evidence_id="news", run_id="r", capability="news", symbol="600519",
        trade_date=date(2026, 7, 31), fetched_at=datetime(2026, 8, 1, 9, 30),
        status=EvidenceStatus.PARTIAL, provider="Anspire",
        payload={"items": [{
            "title": "公司公告", "publisher": "上交所", "published_date": "2026-07-30",
        }]},
    ))

    toolkit = DsaTradingAgentsToolkit(
        ledger, trace_emit=lambda **event: trace.append(event),
    )
    bundle = toolkit.prefetch_sentiment(
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
    assert bundle["news_source"] == "Anspire"
    assert "公司公告" in bundle["news"]
    assert [section["key"] for section in bundle["sections"]] == [
        "domestic_news", "domestic_investor_community",
    ]
    assert "不得要求或虚构 Bullish/Bearish" in bundle["sections"][1]["guidance"]
    assert toolkit.consumed_capabilities == {"news", "sentiment"}
    assert [event["event_type"] for event in trace if event["event_type"].startswith("tool.")] == [
        "tool.started", "tool.completed",
    ]


def test_news_and_sentiment_tools_filter_dated_items_but_retain_undated_with_warning() -> None:
    ledger = EvidenceLedger(
        run_id="r", symbol="600519", trade_date=date(2026, 7, 31), created_at=datetime.now(),
    )
    items = [
        {"title": "窗口内", "published_date": "2026-07-30"},
        {"title": "窗口外", "published_date": "2026-07-01"},
        {"title": "无日期", "published_date": None},
    ]
    ledger.add(EvidenceEnvelope(
        evidence_id="news", run_id="r", capability="news", symbol="600519",
        trade_date=date(2026, 7, 31), fetched_at=datetime.now(), status=EvidenceStatus.OK,
        provider="fixture", payload={"items": items},
    ))

    result = DsaTradingAgentsToolkit(ledger).get_news(
        "600519", "2026-07-24", "2026-07-31",
    )

    assert "窗口内" in result
    assert "窗口外" not in result
    assert "undated_retained_low_confidence" in result


def test_financial_statement_tools_return_only_requested_statement_fields() -> None:
    ledger = EvidenceLedger(
        run_id="r", symbol="600519", trade_date=date(2026, 7, 31), created_at=datetime.now(),
    )
    ledger.add(EvidenceEnvelope(
        evidence_id="fundamentals", run_id="r", capability="fundamentals", symbol="600519",
        trade_date=date(2026, 7, 31), fetched_at=datetime.now(), status=EvidenceStatus.OK,
        provider="tushare", payload={"earnings": {"data": {"financial_report": {
            "report_date": "2026-03-31", "announcement_date": "2026-04-30",
            "revenue": 100, "net_profit_parent": 20, "operating_cash_flow": 30,
            "total_assets": 500, "total_liabilities": 200, "equity_parent": 300,
        }}}},
    ))
    toolkit = DsaTradingAgentsToolkit(ledger)

    income = toolkit.get_income_statement("600519")
    cashflow = toolkit.get_cashflow("600519")
    balance = toolkit.get_balance_sheet("600519")

    assert "revenue" in income and "operating_cash_flow" not in income and "total_assets" not in income
    assert "operating_cash_flow" in cashflow and "revenue" not in cashflow
    assert "total_assets" in balance and "revenue" not in balance


def test_fetch_returns_keeps_memory_pending_without_canonical_benchmark() -> None:
    ledger = EvidenceLedger(
        run_id="r", symbol="600519", trade_date=date(2026, 7, 31), created_at=datetime.now(),
    )
    ledger.add(EvidenceEnvelope(
        evidence_id="daily", run_id="r", capability="market_daily_bars", symbol="600519",
        trade_date=date(2026, 7, 31), fetched_at=datetime.now(), status=EvidenceStatus.OK,
        provider="fixture", payload={"rows": [{"trade_date": "2026-07-31", "close": 100}]},
    ))

    assert DsaTradingAgentsToolkit(ledger).fetch_returns("600519", "2026-07-31") == (None, None, None)
