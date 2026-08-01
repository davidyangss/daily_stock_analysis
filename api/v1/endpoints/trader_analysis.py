# -*- coding: utf-8 -*-
"""Independent trader-analysis API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.deps import get_config_dep
from api.v1.schemas.trader_analysis import (
    TraderAnalysisEvent,
    TraderAnalysisRun,
    TraderAnalysisRunRequest,
    TraderAnalysisTraceEvent,
)
from src.config import Config
from src.trader_analysis.task_service import TraderAnalysisCapacityError, get_trader_analysis_task_service

router = APIRouter()


def _not_found(run_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "trader_analysis_run_not_found", "message": f"交易员分析运行 {run_id} 不存在或已过期"},
    )


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED, response_model=TraderAnalysisRun)
def create_trader_analysis_run(
    payload: TraderAnalysisRunRequest,
    config: Config = Depends(get_config_dep),
) -> TraderAnalysisRun:
    try:
        return get_trader_analysis_task_service().submit(
            symbol=payload.symbol,
            trade_date=payload.trade_date,
            app_config=config,
        )
    except TraderAnalysisCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "trader_analysis_queue_full", "message": str(exc)},
        ) from exc


@router.get("/runs/{run_id}", response_model=TraderAnalysisRun)
def get_trader_analysis_run(run_id: str) -> TraderAnalysisRun:
    run = get_trader_analysis_task_service().get(run_id)
    if run is None:
        raise _not_found(run_id)
    return run


@router.get("/runs/{run_id}/events", response_model=list[TraderAnalysisEvent])
def get_trader_analysis_events(
    run_id: str,
    after: int = Query(0, ge=0),
) -> list[TraderAnalysisEvent]:
    if get_trader_analysis_task_service().get(run_id) is None:
        raise _not_found(run_id)
    return get_trader_analysis_task_service().events(run_id, after=after)


@router.get("/runs/{run_id}/trace", response_model=list[TraderAnalysisTraceEvent])
def get_trader_analysis_trace(run_id: str, after: int = Query(0, ge=0)) -> list[TraderAnalysisTraceEvent]:
    if get_trader_analysis_task_service().get(run_id) is None:
        raise _not_found(run_id)
    return get_trader_analysis_task_service().trace(run_id, after=after)


@router.post("/runs/{run_id}/cancel", response_model=TraderAnalysisRun)
def cancel_trader_analysis_run(run_id: str) -> TraderAnalysisRun:
    run = get_trader_analysis_task_service().cancel(run_id)
    if run is None:
        raise _not_found(run_id)
    return run
