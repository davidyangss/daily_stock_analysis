from datetime import date, datetime

from src.trader_analysis.evidence.ledger import create_ledger
from src.trader_analysis.evidence.policy import evaluate_overall_status
from src.trader_analysis.identity.resolver import UnsupportedInstrumentError, normalize_a_share_symbol
from src.trader_analysis.schemas.evidence import EvidenceEnvelope, EvidenceIssue, EvidenceIssueSeverity, EvidenceStatus


def _envelope(capability: str, status: EvidenceStatus = EvidenceStatus.OK, issues=None) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        evidence_id=f"ev-{capability}",
        run_id="run-1",
        capability=capability,
        symbol="600519",
        trade_date=date(2026, 7, 31),
        fetched_at=datetime(2026, 7, 31, 12, 0, 0),
        status=status,
        provider="test",
        source_chain=["test"],
        issues=issues or [],
        payload={},
    )


def test_normalize_a_share_symbol_accepts_common_forms():
    assert normalize_a_share_symbol("600519") == ("600519", "SH")
    assert normalize_a_share_symbol("600519.SH") == ("600519", "SH")
    assert normalize_a_share_symbol("SZ000001") == ("000001", "SZ")
    assert normalize_a_share_symbol("BJ920748") == ("920748", "BJ")


def test_normalize_a_share_symbol_rejects_non_a_share_forms():
    for value in ["AAPL", "00700.HK", "510300", "SH000001", "600519.SZ"]:
        try:
            normalize_a_share_symbol(value)
        except UnsupportedInstrumentError:
            continue
        raise AssertionError(f"{value} should be rejected")


def test_quality_policy_requires_market_and_snapshot():
    ledger = create_ledger("run-1", "600519", date(2026, 7, 31))
    ledger.add(_envelope("market_daily_bars"))
    assert evaluate_overall_status(ledger) == "insufficient_evidence"


def test_quality_policy_marks_warning_as_degraded():
    ledger = create_ledger("run-1", "600519", date(2026, 7, 31))
    warning = EvidenceIssue(
        code="community_sentiment_unavailable",
        severity=EvidenceIssueSeverity.WARNING,
        capability="sentiment",
        provider=None,
        message="社区情绪不可用",
    )
    ledger.add(_envelope("market_daily_bars"))
    ledger.add(_envelope("verified_market_snapshot"))
    ledger.add(_envelope("sentiment", EvidenceStatus.PARTIAL, [warning]))
    ledger.add(_envelope("news"))
    assert evaluate_overall_status(ledger) == "degraded"


def test_quality_policy_marks_complete_when_core_and_two_optional_are_clean():
    ledger = create_ledger("run-1", "600519", date(2026, 7, 31))
    ledger.add(_envelope("market_daily_bars"))
    ledger.add(_envelope("verified_market_snapshot"))
    ledger.add(_envelope("news"))
    ledger.add(_envelope("fundamentals"))
    assert evaluate_overall_status(ledger) == "complete"
