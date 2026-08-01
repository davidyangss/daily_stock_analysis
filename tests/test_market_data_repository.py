from datetime import date
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from src.repositories.market_data_repo import MarketDataRepository
from data_provider.base import DataFetcherManager


def _frame(close: float = 10.5, *, include_today: bool = False) -> pd.DataFrame:
    rows = [{
        "date": "2026-07-30", "open": 10.0, "high": 11.0, "low": 9.0,
        "close": close, "volume": 1000, "amount": 10500, "pct_chg": 1.2,
        "ma5": 10.1, "ma10": 10.2, "ma20": 10.3, "volume_ratio": 1.0,
    }]
    if include_today:
        rows.append({**rows[0], "date": date.today().isoformat(), "close": 99.0})
    return pd.DataFrame(rows)


def test_repository_upserts_revisions_and_skips_identical_observations(tmp_path) -> None:
    path = tmp_path / "market_data.db"
    repository = MarketDataRepository(path)

    first = repository.upsert_historical_bars(
        _frame(), market="cn", symbol="603986", adjustment="qfq",
        provider="TencentFetcher", before_date=date.today(),
    )
    identical = repository.upsert_historical_bars(
        _frame(), market="cn", symbol="603986", adjustment="qfq",
        provider="TencentFetcher", before_date=date.today(),
    )
    revised = repository.upsert_historical_bars(
        _frame(10.8), market="cn", symbol="603986", adjustment="qfq",
        provider="TencentFetcher", before_date=date.today(),
    )

    assert first == {"inserted": 1, "revised": 0, "unchanged": 0}
    assert identical == {"inserted": 0, "revised": 0, "unchanged": 1}
    assert revised == {"inserted": 0, "revised": 1, "unchanged": 0}
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT close, revision FROM daily_bars").fetchone()
        observations = connection.execute("SELECT COUNT(*) FROM daily_bar_observations").fetchone()[0]
    assert row == (10.8, 2)
    assert observations == 2


def test_repository_never_persists_today_and_keeps_adjustments_separate(tmp_path) -> None:
    repository = MarketDataRepository(tmp_path / "market_data.db")
    repository.upsert_historical_bars(
        _frame(include_today=True), market="cn", symbol="603986", adjustment="qfq",
        provider="TencentFetcher", before_date=date.today(),
    )
    repository.upsert_historical_bars(
        _frame(20.0), market="cn", symbol="603986", adjustment="none",
        provider="TushareFetcher", before_date=date.today(),
    )

    qfq = repository.load_daily_bars(
        market="cn", symbol="603986", adjustment="qfq",
        start_date=date(2026, 1, 1), end_date=date.today(),
    )
    unadjusted = repository.load_daily_bars(
        market="cn", symbol="603986", adjustment="none",
        start_date=date(2026, 1, 1), end_date=date.today(),
    )
    assert len(qfq) == 1
    assert len(unadjusted) == 1
    assert float(qfq.iloc[0]["close"]) == 10.5
    assert float(unadjusted.iloc[0]["close"]) == 20.0


def test_manager_fetches_persists_then_reads_historical_window_from_cache(tmp_path) -> None:
    dates = pd.bdate_range(end="2026-07-30", periods=35)
    frame = pd.DataFrame({
        "date": dates, "open": 10.0, "high": 11.0, "low": 9.0,
        "close": 10.5, "volume": 1000.0, "amount": 10500.0, "pct_chg": 1.2,
        "ma5": 10.1, "ma10": 10.2, "ma20": 10.3, "volume_ratio": 1.0,
    })
    fetcher = MagicMock()
    fetcher.name = "TencentFetcher"
    fetcher.priority = 0
    fetcher.get_daily_data.return_value = frame
    config = SimpleNamespace(
        daily_source_priority="tencent",
        market_data_cache_enabled=True,
        market_data_database_path=str(tmp_path / "market_data.db"),
    )

    with patch("src.config.get_config", return_value=config):
        first_manager = DataFetcherManager(fetchers=[fetcher])
        first, first_source = first_manager.get_daily_data(
            "603986", end_date="2026-07-30", days=30, min_rows=30,
        )
        second_manager = DataFetcherManager(fetchers=[fetcher])
        second, second_source = second_manager.get_daily_data(
            "603986", end_date="2026-07-30", days=30, min_rows=30,
        )

    assert len(first) == 35
    assert first_source == "TencentFetcher"
    assert len(second) == 35
    assert second_source == "market_data_db"
    fetcher.get_daily_data.assert_called_once()
