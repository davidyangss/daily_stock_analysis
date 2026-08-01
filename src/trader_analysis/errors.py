"""Safe error helpers for trader-analysis APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from src.trader_analysis.schemas.result import TraderAnalysisError


def build_error(
    *,
    code: str,
    message: str,
    stage: str,
    run_id: Optional[str] = None,
    capability: Optional[str] = None,
    provider: Optional[str] = None,
    retriable: bool = False,
    details: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> TraderAnalysisError:
    return TraderAnalysisError(
        code=code,
        message=message,
        stage=stage,
        run_id=run_id,
        capability=capability,
        provider=provider,
        retriable=retriable,
        trace_id=trace_id or uuid.uuid4().hex,
        details=details or {},
        occurred_at=datetime.now(),
    )
