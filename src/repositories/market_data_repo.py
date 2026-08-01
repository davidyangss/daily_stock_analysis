"""SQLite repository for normalized historical market data."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_bars (
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    adjustment TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume_shares REAL,
    amount REAL,
    pct_change REAL,
    ma5 REAL,
    ma10 REAL,
    ma20 REAL,
    volume_ratio REAL,
    provider TEXT NOT NULL,
    quality_status TEXT NOT NULL DEFAULT 'valid',
    payload_hash TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    fetched_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (market, symbol, adjustment, trade_date)
);
CREATE INDEX IF NOT EXISTS ix_daily_bars_symbol_date
ON daily_bars (market, symbol, adjustment, trade_date);
CREATE INDEX IF NOT EXISTS ix_daily_bars_trade_date
ON daily_bars (trade_date);
CREATE TABLE IF NOT EXISTS daily_bar_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    adjustment TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    provider TEXT NOT NULL,
    normalized_payload TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    revision INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_daily_bar_observations_identity
ON daily_bar_observations (market, symbol, adjustment, trade_date, fetched_at);
"""


class MarketDataRepository:
    """Store stable historical bars and auditable provider revisions."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema(connection)
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if not self._initialized:
                connection.executescript(_SCHEMA)
                connection.commit()
                self._initialized = True

    def load_daily_bars(
        self,
        *,
        market: str,
        symbol: str,
        adjustment: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT trade_date AS date, open, high, low, close,
                       volume_shares AS volume, amount, pct_change AS pct_chg,
                       ma5, ma10, ma20, volume_ratio, provider AS data_source
                FROM daily_bars
                WHERE market = ? AND symbol = ? AND adjustment = ?
                  AND trade_date BETWEEN ? AND ? AND quality_status = 'valid'
                ORDER BY trade_date
                """,
                (market, symbol, adjustment, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame([dict(row) for row in rows])
        frame["date"] = pd.to_datetime(frame["date"])
        return frame

    def load_best_daily_bars(
        self,
        *,
        market: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> tuple[pd.DataFrame, Optional[str]]:
        """Return one internally consistent adjustment series, never a mixed one."""
        with self._connect() as connection:
            candidates = connection.execute(
                """
                SELECT adjustment, COUNT(*) AS row_count, MAX(trade_date) AS last_date
                FROM daily_bars
                WHERE market=? AND symbol=? AND trade_date BETWEEN ? AND ?
                  AND quality_status='valid'
                GROUP BY adjustment
                ORDER BY row_count DESC, last_date DESC
                """,
                (market, symbol, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        if not candidates:
            return pd.DataFrame(), None
        adjustment = str(candidates[0]["adjustment"])
        return self.load_daily_bars(
            market=market,
            symbol=symbol,
            adjustment=adjustment,
            start_date=start_date,
            end_date=end_date,
        ), adjustment

    def upsert_historical_bars(
        self,
        df: pd.DataFrame,
        *,
        market: str,
        symbol: str,
        adjustment: str,
        provider: str,
        before_date: date,
    ) -> Dict[str, int]:
        counts = {"inserted": 0, "revised": 0, "unchanged": 0}
        if df is None or df.empty:
            return counts
        fetched_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for raw in df.to_dict(orient="records"):
                parsed_date = pd.to_datetime(raw.get("date"), errors="coerce")
                if pd.isna(parsed_date):
                    continue
                trade_date = parsed_date.date()
                if trade_date >= before_date:
                    continue
                payload = self._payload(raw)
                payload_hash = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                existing = connection.execute(
                    """SELECT payload_hash, revision FROM daily_bars
                       WHERE market=? AND symbol=? AND adjustment=? AND trade_date=?""",
                    (market, symbol, adjustment, trade_date.isoformat()),
                ).fetchone()
                if existing and existing["payload_hash"] == payload_hash:
                    counts["unchanged"] += 1
                    continue
                revision = int(existing["revision"]) + 1 if existing else 1
                outcome = "revised" if existing else "inserted"
                counts[outcome] += 1
                values = (
                    market, symbol, adjustment, trade_date.isoformat(),
                    payload["open"], payload["high"], payload["low"], payload["close"],
                    payload["volume"], payload["amount"], payload["pct_chg"],
                    payload["ma5"], payload["ma10"], payload["ma20"], payload["volume_ratio"],
                    provider, payload_hash, revision, fetched_at, fetched_at, fetched_at,
                )
                connection.execute(
                    """
                    INSERT INTO daily_bars (
                        market,symbol,adjustment,trade_date,open,high,low,close,
                        volume_shares,amount,pct_change,ma5,ma10,ma20,volume_ratio,
                        provider,payload_hash,revision,fetched_at,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(market,symbol,adjustment,trade_date) DO UPDATE SET
                        open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                        volume_shares=excluded.volume_shares, amount=excluded.amount,
                        pct_change=excluded.pct_change, ma5=excluded.ma5, ma10=excluded.ma10,
                        ma20=excluded.ma20, volume_ratio=excluded.volume_ratio,
                        provider=excluded.provider, quality_status='valid',
                        payload_hash=excluded.payload_hash, revision=excluded.revision,
                        fetched_at=excluded.fetched_at, updated_at=excluded.updated_at
                    """,
                    values,
                )
                connection.execute(
                    """INSERT INTO daily_bar_observations (
                        market,symbol,adjustment,trade_date,provider,normalized_payload,
                        payload_hash,revision,outcome,fetched_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        market, symbol, adjustment, trade_date.isoformat(), provider,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True), payload_hash,
                        revision, outcome, fetched_at,
                    ),
                )
            connection.commit()
        return counts

    @staticmethod
    def _payload(row: Dict[str, Any]) -> Dict[str, Optional[float]]:
        def number(name: str) -> Optional[float]:
            value = row.get(name)
            if value is None or pd.isna(value):
                return None
            return float(value)

        return {
            "open": number("open"), "high": number("high"), "low": number("low"),
            "close": number("close"), "volume": number("volume"), "amount": number("amount"),
            "pct_chg": number("pct_chg"), "ma5": number("ma5"), "ma10": number("ma10"),
            "ma20": number("ma20"), "volume_ratio": number("volume_ratio"),
        }
