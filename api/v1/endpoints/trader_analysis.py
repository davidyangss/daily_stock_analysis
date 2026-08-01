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
from src.trader_analysis.schemas.result import TraderTaskStatus
from src.trader_analysis.task_service import TraderAnalysisCapacityError, get_trader_analysis_task_service

router = APIRouter()


def _service(config: Config):
    service = get_trader_analysis_task_service()
    service.configure(config)
    return service


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


@router.get("/runs", response_model=list[TraderAnalysisRun])
def list_trader_analysis_runs(
    task_status: list[str] = Query(default=[]),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    config: Config = Depends(get_config_dep),
) -> list[TraderAnalysisRun]:
    """List durable trader-analysis tasks, newest first."""
    valid_statuses = {item.value for item in TraderTaskStatus}
    invalid_statuses = sorted(set(task_status) - valid_statuses)
    if invalid_statuses:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_trader_analysis_task_status",
                "message": f"不支持的任务状态：{', '.join(invalid_statuses)}",
            },
        )
    return _service(config).list_runs(statuses=task_status, offset=offset, limit=limit)


@router.get("/runs/{run_id}", response_model=TraderAnalysisRun)
def get_trader_analysis_run(run_id: str, config: Config = Depends(get_config_dep)) -> TraderAnalysisRun:
    run = _service(config).get(run_id)
    if run is None:
        raise _not_found(run_id)
    return run


@router.get("/runs/{run_id}/events", response_model=list[TraderAnalysisEvent])
def get_trader_analysis_events(
    run_id: str,
    after: int = Query(0, ge=0),
    config: Config = Depends(get_config_dep),
) -> list[TraderAnalysisEvent]:
    service = _service(config)
    if service.get(run_id) is None:
        raise _not_found(run_id)
    return service.events(run_id, after=after)


@router.get("/runs/{run_id}/trace", response_model=list[TraderAnalysisTraceEvent])
def get_trader_analysis_trace(
    run_id: str,
    after: int = Query(0, ge=0),
    config: Config = Depends(get_config_dep),
) -> list[TraderAnalysisTraceEvent]:
    service = _service(config)
    if service.get(run_id) is None:
        raise _not_found(run_id)
    return service.trace(run_id, after=after)


@router.post("/runs/{run_id}/cancel", response_model=TraderAnalysisRun)
def cancel_trader_analysis_run(run_id: str, config: Config = Depends(get_config_dep)) -> TraderAnalysisRun:
    run = _service(config).cancel(run_id)
    if run is None:
        raise _not_found(run_id)
    return run
