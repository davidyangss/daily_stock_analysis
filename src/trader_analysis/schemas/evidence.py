"""Canonical evidence contracts for trader-analysis tools."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class EvidenceStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    STALE = "stale"


class EvidenceIssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class FallbackAttempt(BaseModel):
    provider: str
    started_at: datetime
    finished_at: datetime
    outcome: Literal[
        "ok",
        "partial",
        "not_configured",
        "not_supported",
        "timeout",
        "rate_limited",
        "empty",
        "invalid",
        "error",
    ]
    error_type: Optional[str] = None
    error_message: Optional[str] = None


class EvidenceIssue(BaseModel):
    code: str
    severity: EvidenceIssueSeverity
    capability: str
    provider: Optional[str] = None
    message: str
    missing_fields: List[str] = Field(default_factory=list)
    expected: Optional[Dict[str, Any]] = None
    observed: Optional[Dict[str, Any]] = None
    retriable: bool = False


class EvidenceEnvelope(BaseModel):
    schema_version: Literal["trader-evidence-v1"] = "trader-evidence-v1"
    evidence_id: str
    run_id: str
    capability: str
    symbol: str
    market: Literal["cn"] = "cn"
    currency: Literal["CNY"] = "CNY"
    trade_date: date
    as_of: Optional[datetime] = None
    fetched_at: datetime
    status: EvidenceStatus
    provider: Optional[str] = None
    source_chain: List[str] = Field(default_factory=list)
    fallback_trace: List[FallbackAttempt] = Field(default_factory=list)
    is_stale: Optional[bool] = None
    stale_seconds: Optional[int] = None
    missing_fields: List[str] = Field(default_factory=list)
    issues: List[EvidenceIssue] = Field(default_factory=list)
    payload: Optional[Dict[str, Any]] = None


class EvidenceLedger(BaseModel):
    run_id: str
    symbol: str
    trade_date: date
    created_at: datetime
    envelopes: Dict[str, EvidenceEnvelope] = Field(default_factory=dict)
    blocking_issues: List[EvidenceIssue] = Field(default_factory=list)
    warnings: List[EvidenceIssue] = Field(default_factory=list)
    providers_used: List[str] = Field(default_factory=list)
    overall_status: Literal["complete", "degraded", "insufficient_evidence"] = "insufficient_evidence"

    def add(self, envelope: EvidenceEnvelope) -> None:
        self.envelopes[envelope.capability] = envelope
        if envelope.provider and envelope.provider not in self.providers_used:
            self.providers_used.append(envelope.provider)
        for issue in envelope.issues:
            if issue.severity == EvidenceIssueSeverity.BLOCKING:
                self.blocking_issues.append(issue)
            elif issue.severity == EvidenceIssueSeverity.WARNING:
                self.warnings.append(issue)
