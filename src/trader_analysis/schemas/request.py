"""Request schemas for trader-analysis orchestration."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class TraderAnalysisRunRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24)
    trade_date: date
