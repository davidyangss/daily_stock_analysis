from datetime import date, datetime
from unittest.mock import Mock

import pandas as pd

from src.trader_analysis.adapters.market import MarketEvidenceAdapter
from src.trader_analysis.schemas.evidence import EvidenceEnvelope, EvidenceStatus


def _daily_frame(rows: int = 35) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-07-30", periods=rows)
    return pd.DataFrame({
        "date": dates,
        "open": [100.0] * rows,
        "high": [102.0] * rows,
        "low": [99.0] * rows,
        "close": [101.0] * rows,
        "volume": [1000] * rows,
    })


def test_daily_bars_accepts_manager_frame_provider_tuple() -> None:
    manager = Mock()
    manager.get_daily_data.return_value = (_daily_frame(), "IwencaiFetcher")

    evidence = MarketEvidenceAdapter(manager).fetch_daily_bars(
        run_id="run-1",
        symbol="603986",
        trade_date=date(2026, 7, 30),
        min_daily_bars=30,
    )

    assert evidence.status == EvidenceStatus.OK
    assert evidence.provider == "IwencaiFetcher"
    assert evidence.payload["last_date"] == "2026-07-30"
    assert evidence.payload["trading_days"] == 35
    manager.get_daily_data.assert_called_once_with(
        "603986",
        end_date="2026-07-30",
        days=260,
        min_rows=30,
        preferred_adjustments=("qfq", "auto_adjust"),
    )


def test_daily_bars_exposes_provider_adjustment_without_guessing() -> None:
    manager = Mock()
    manager.get_daily_data.return_value = (_daily_frame(), "AkshareFetcher")

    evidence = MarketEvidenceAdapter(manager).fetch_daily_bars(
        run_id="run-adjustment",
        symbol="603986",
        trade_date=date(2026, 7, 30),
        min_daily_bars=30,
    )

    assert evidence.payload["adjustment"] == "qfq"

    manager.get_daily_data.return_value = (_daily_frame(), "unmapped-provider")
    unknown = MarketEvidenceAdapter(manager).fetch_daily_bars(
        run_id="run-unknown-adjustment",
        symbol="603986",
        trade_date=date(2026, 7, 30),
        min_daily_bars=30,
    )

    assert unknown.payload["adjustment"] == "unknown"


def test_single_invalid_historical_bar_warns_but_does_not_stop_analysis() -> None:
    frame = _daily_frame()
    frame.loc[0, "low"] = 103.0
    manager = Mock()
    manager.get_daily_data.return_value = (frame, "example-provider")

    evidence = MarketEvidenceAdapter(manager).fetch_daily_bars(
        run_id="run-2",
        symbol="603986",
        trade_date=date(2026, 7, 30),
        min_daily_bars=30,
    )

    assert evidence.status == EvidenceStatus.PARTIAL
    assert evidence.payload["trading_days"] == 34
    assert evidence.issues[0].code == "provider_invalid_payload"
    assert evidence.issues[0].severity.value == "warning"


def test_new_listing_short_history_degrades_without_blocking() -> None:
    manager = Mock()
    manager.get_daily_data.return_value = (_daily_frame(3), "TushareFetcher")

    evidence = MarketEvidenceAdapter(manager).fetch_daily_bars(
        run_id="new-listing",
        symbol="688825",
        trade_date=date(2026, 7, 30),
        min_daily_bars=30,
    )

    assert evidence.status == EvidenceStatus.PARTIAL
    assert evidence.payload["trading_days"] == 3
    assert [issue.code for issue in evidence.issues] == ["limited_daily_history"]
    assert evidence.issues[0].severity.value == "warning"


def test_unadjusted_corporate_action_recomputes_return_and_bounds_indicators() -> None:
    frame = pd.DataFrame({
        "date": pd.to_datetime(["2026-05-08", "2026-05-11", "2026-05-12"]),
        "open": [87.1, 59.5, 59.22],
        "high": [87.1, 60.3, 59.47],
        "low": [83.36, 58.5, 57.42],
        "close": [86.27, 59.21, 58.14],
        "volume": [1000, 1200, 900],
        "pct_chg": [-1.2364, 0.6802, -1.8071],
    })
    manager = Mock()
    manager.get_daily_data.return_value = (frame, "TushareFetcher")

    evidence = MarketEvidenceAdapter(manager).fetch_daily_bars(
        run_id="corporate-action",
        symbol="002595",
        trade_date=date(2026, 5, 12),
        min_daily_bars=3,
    )

    rows = evidence.payload["rows"]
    assert rows[1]["pct_change"] == -31.36664
    assert rows[1]["provider_pct_change"] == 0.6802
    assert evidence.payload["indicator_start_date"] == "2026-05-11"
    assert evidence.payload["corporate_action_breaks"] == [{
        "trade_date": "2026-05-11",
        "derived_pct_change": -31.36664,
        "provider_pct_change": 0.6802,
    }]
    assert [issue.code for issue in evidence.issues] == [
        "daily_pct_change_recomputed",
        "unadjusted_corporate_action_break",
    ]
    assert evidence.status == EvidenceStatus.PARTIAL


def _daily_envelope_for_snapshot() -> EvidenceEnvelope:
    return EvidenceEnvelope(
        evidence_id="daily", run_id="snapshot", capability="market_daily_bars",
        symbol="603986", trade_date=date.today(), fetched_at=datetime.now(),
        status=EvidenceStatus.OK, provider="daily-provider", is_stale=False,
        payload={"rows": [{"trade_date": date.today().isoformat(), "close": 100.0}]},
    )


def test_realtime_snapshot_rejects_wrong_exchange_suffix_for_same_digits() -> None:
    manager = Mock()
    manager.get_realtime_quote.return_value = {
        "code": "603986.SZ", "price": 101.0, "source": "quote-provider",
    }

    evidence = MarketEvidenceAdapter(manager).fetch_snapshot(
        run_id="snapshot", symbol="603986", trade_date=date.today(),
        daily_envelope=_daily_envelope_for_snapshot(),
    )

    assert evidence.status == EvidenceStatus.INVALID
    assert [issue.code for issue in evidence.issues] == ["identity_mismatch"]


def test_realtime_snapshot_requires_quote_identity_and_preserves_provider_time() -> None:
    provider_time = "2026-08-02T09:31:02+08:00"
    manager = Mock()
    manager.get_realtime_quote.return_value = {
        "price": 101.0,
        "source": "quote-provider",
        "provider_timestamp": provider_time,
        "fetched_at": "2026-08-02T09:31:03+08:00",
        "is_stale": True,
        "stale_seconds": 61,
    }

    evidence = MarketEvidenceAdapter(manager).fetch_snapshot(
        run_id="snapshot", symbol="603986", trade_date=date.today(),
        daily_envelope=_daily_envelope_for_snapshot(),
    )

    assert evidence.status == EvidenceStatus.INVALID
    assert [issue.code for issue in evidence.issues] == ["identity_mismatch"]
    assert evidence.payload["quote_time"] == provider_time
    assert evidence.payload["quote_fetched_at"] == "2026-08-02T09:31:03+08:00"
    assert evidence.as_of == datetime.fromisoformat(provider_time)
    assert evidence.is_stale is True
    assert evidence.stale_seconds == 61
