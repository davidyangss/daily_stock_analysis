"""Ledger helpers."""

from __future__ import annotations

from datetime import date, datetime

from src.trader_analysis.schemas.evidence import EvidenceLedger


def create_ledger(run_id: str, symbol: str, trade_date: date) -> EvidenceLedger:
    return EvidenceLedger(
        run_id=run_id,
        symbol=symbol,
        trade_date=trade_date,
        created_at=datetime.now(),
    )
