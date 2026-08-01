from datetime import date
from unittest.mock import Mock

import pandas as pd

from src.trader_analysis.adapters.market import MarketEvidenceAdapter
from src.trader_analysis.schemas.evidence import EvidenceStatus


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
        min_rows=1,
    )


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
