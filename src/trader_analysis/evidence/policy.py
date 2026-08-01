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
    # Core point-in-time market evidence is sufficient to run the graph in a
    # constrained mode. Optional evidence gaps must remain visible in the
    # quality report and keep the result degraded, but must not suppress every
    # analyst report for historical dates where look-ahead is intentionally
    # prohibited.
    return "degraded"
