"""Durable, sanitized execution trace schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TraderAnalysisTraceEvent(BaseModel):
    run_id: str
    sequence: int
    event_type: str
    stage: str
    role: str | None = None
    deployment_name: str | None = None
    provider: str | None = None
    model: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
