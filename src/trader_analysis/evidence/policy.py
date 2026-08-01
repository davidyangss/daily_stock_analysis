"""Deterministic quality policy for trader-analysis evidence."""

from __future__ import annotations

from src.trader_analysis.schemas.evidence import EvidenceLedger, EvidenceStatus


def evaluate_overall_status(ledger: EvidenceLedger) -> str:
    if ledger.blocking_issues:
        return "insufficient_evidence"

    market = ledger.envelopes.get("market_daily_bars")
    snapshot = ledger.envelopes.get("verified_market_snapshot")
    if market is None or market.status not in {EvidenceStatus.OK, EvidenceStatus.PARTIAL}:
        return "insufficient_evidence"
    if snapshot is None or snapshot.status not in {EvidenceStatus.OK, EvidenceStatus.PARTIAL}:
        return "insufficient_evidence"

    usable_optional = 0
    for capability in ("sentiment", "news", "fundamentals"):
        envelope = ledger.envelopes.get(capability)
        if envelope and envelope.status in {EvidenceStatus.OK, EvidenceStatus.PARTIAL}:
            usable_optional += 1

    if usable_optional >= 2:
        return "degraded" if ledger.warnings else "complete"
    if usable_optional == 1:
        return "degraded"
    return "insufficient_evidence"
