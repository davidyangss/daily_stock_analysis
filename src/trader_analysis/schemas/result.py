"""Task and result schemas for trader analysis."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.trader_analysis.schemas.evidence import EvidenceIssue
from src.trader_analysis.schemas.instrument import InstrumentContext


class TraderTaskStatus(str, Enum):
    PENDING = "pending"
    PREFLIGHTING = "preflighting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TraderAnalysisStatus(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class TraderAnalysisError(BaseModel):
    code: str
    message: str
    stage: str
    run_id: Optional[str] = None
    capability: Optional[str] = None
    provider: Optional[str] = None
    retriable: bool = False
    trace_id: str
    details: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


class TraderAnalysisReport(BaseModel):
    kind: str
    title: str
    content: str


class TraderAnalysisQualitySummary(BaseModel):
    providers_used: List[str] = Field(default_factory=list)
    warnings: List[EvidenceIssue] = Field(default_factory=list)
    blocking_issues: List[EvidenceIssue] = Field(default_factory=list)
    overall_status: Optional[str] = None


class TraderAnalysisRun(BaseModel):
    run_id: str
    task_status: TraderTaskStatus
    analysis_status: Optional[TraderAnalysisStatus] = None
    symbol: str
    trade_date: date
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_stage: str = "pending"
    instrument: Optional[InstrumentContext] = None
    quality: TraderAnalysisQualitySummary = Field(default_factory=TraderAnalysisQualitySummary)
    reports: List[TraderAnalysisReport] = Field(default_factory=list)
    error: Optional[TraderAnalysisError] = None
    links: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TraderAnalysisEvent(BaseModel):
    run_id: str
    sequence: int
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
