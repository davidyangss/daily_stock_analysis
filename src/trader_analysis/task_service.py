"""Independent async task service for trader analysis."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Dict, Optional

from src.config import Config
from src.trader_analysis.config import TraderAnalysisConfig
from src.trader_analysis.errors import build_error
from src.trader_analysis.orchestrator import TraderAnalysisOrchestrator, new_run_id
from src.trader_analysis.persistence.repository import TraderAnalysisRepository, get_trader_analysis_repository
from src.trader_analysis.schemas.result import TraderAnalysisEvent, TraderAnalysisRun, TraderTaskStatus
from src.trader_analysis.schemas.trace import TraderAnalysisTraceEvent


class TraderAnalysisCapacityError(RuntimeError):
    pass


class TraderAnalysisTaskService:
    _instance: Optional["TraderAnalysisTaskService"] = None
    _lock = threading.Lock()

    def __init__(self, repository: Optional[TraderAnalysisRepository] = None) -> None:
        self.repository = repository or get_trader_analysis_repository()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._cancel_flags: Dict[str, threading.Event] = {}
        self._sequence: Dict[str, int] = {}
        self._trace_sequence: Dict[str, int] = {}
        self._state_lock = threading.Lock()
        self._active_and_queued = 0

    @classmethod
    def get_instance(cls) -> "TraderAnalysisTaskService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def submit(self, *, symbol: str, trade_date: date, app_config: Config) -> TraderAnalysisRun:
        service_config = TraderAnalysisConfig.from_app_config(app_config)
        self.repository.configure(service_config.results_dir)
        with self._state_lock:
            if self._active_and_queued >= service_config.queue_limit:
                raise TraderAnalysisCapacityError("交易员分析队列已满，请稍后重试")
            self._active_and_queued += 1
        run_id = new_run_id()
        run = TraderAnalysisRun(
            run_id=run_id,
            task_status=TraderTaskStatus.PENDING,
            symbol=symbol,
            trade_date=trade_date,
            created_at=datetime.now(),
            links={
                "self": f"/api/v1/trader-analysis/runs/{run_id}",
                "events": f"/api/v1/trader-analysis/runs/{run_id}/events",
                "trace": f"/api/v1/trader-analysis/runs/{run_id}/trace",
            },
            metadata={
                "tradingagents_version": service_config.tradingagents_version,
                "tradingagents_commit": service_config.tradingagents_commit,
                "data_toolkit_version": service_config.data_toolkit_version,
                "evidence_policy_version": service_config.evidence_policy_version,
            },
        )
        self.repository.save_run(run)
        self._cancel_flags[run_id] = threading.Event()
        self._emit(run_id, "run.created", {"symbol": symbol, "trade_date": trade_date.isoformat()})

        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=service_config.max_concurrency,
                thread_name_prefix="trader_analysis_",
            )
        self._executor.submit(self._run, run_id, symbol, trade_date, service_config)
        return run

    def get(self, run_id: str) -> Optional[TraderAnalysisRun]:
        return self.repository.get_run(run_id)

    def configure(self, app_config: Config) -> None:
        service_config = TraderAnalysisConfig.from_app_config(app_config)
        self.repository.configure(service_config.results_dir)

    def list_runs(
        self,
        *,
        statuses: Optional[list[str]] = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[TraderAnalysisRun]:
        return self.repository.list_runs(statuses=statuses, offset=offset, limit=limit)

    def events(self, run_id: str, after: int = 0) -> list[TraderAnalysisEvent]:
        return self.repository.list_events(run_id, after=after)

    def trace(self, run_id: str, after: int = 0) -> list[TraderAnalysisTraceEvent]:
        return self.repository.list_trace(run_id, after=after)

    def cancel(self, run_id: str) -> Optional[TraderAnalysisRun]:
        flag = self._cancel_flags.get(run_id)
        if flag is not None:
            flag.set()
        run = self.repository.get_run(run_id)
        cancellable = {
            TraderTaskStatus.PENDING,
            TraderTaskStatus.PREFLIGHTING,
            TraderTaskStatus.RUNNING,
        }
        if run and run.task_status in cancellable:
            run.task_status = TraderTaskStatus.CANCELLED
            run.current_stage = "cancelled"
            run.completed_at = datetime.now()
            self.repository.save_run(run)
            self._emit(run_id, "run.cancelled", {})
        return run

    def _run(self, run_id: str, symbol: str, trade_date: date, service_config: TraderAnalysisConfig) -> None:
        flag = self._cancel_flags[run_id]
        timer = threading.Timer(service_config.task_timeout_seconds, self._timeout, args=(run_id, flag))
        timer.daemon = True
        timer.start()
        try:
            current = self.repository.get_run(run_id)
            if current is not None:
                current.task_status = TraderTaskStatus.PREFLIGHTING
                current.current_stage = "preflighting"
                current.started_at = datetime.now()
                self.repository.save_run(current)
            orchestrator = TraderAnalysisOrchestrator(config=service_config)
            run = orchestrator.run(
                run_id=run_id,
                symbol=symbol,
                trade_date=trade_date,
                emit=lambda event_type, payload: self._emit(run_id, event_type, payload),
                is_cancelled=flag.is_set,
                trace_emit=lambda **values: self._emit_trace(run_id, **values),
            )
            run.links = {
                "self": f"/api/v1/trader-analysis/runs/{run_id}",
                "events": f"/api/v1/trader-analysis/runs/{run_id}/events",
                "trace": f"/api/v1/trader-analysis/runs/{run_id}/trace",
            }
            self.repository.save_run(run)
        except Exception as exc:
            failed = self.repository.get_run(run_id)
            if failed is not None and failed.task_status != TraderTaskStatus.CANCELLED:
                failed.task_status = TraderTaskStatus.FAILED
                failed.current_stage = "failed"
                failed.completed_at = datetime.now()
                failed.error = build_error(
                    code="task_execution_failed",
                    message="交易员分析任务执行失败",
                    stage="task_service",
                    run_id=run_id,
                    retriable=True,
                    details={"error_type": type(exc).__name__},
                )
                self.repository.save_run(failed)
                self._emit(run_id, "run.failed", {"code": failed.error.code, "trace_id": failed.error.trace_id})
        finally:
            timer.cancel()
            with self._state_lock:
                self._active_and_queued = max(0, self._active_and_queued - 1)
            self._cancel_flags.pop(run_id, None)

    def _timeout(self, run_id: str, flag: threading.Event) -> None:
        flag.set()
        self._emit(run_id, "run.timeout", {})

    def _emit(self, run_id: str, event_type: str, payload: dict) -> TraderAnalysisEvent:
        with self._state_lock:
            sequence = self._sequence.get(run_id, 0) + 1
            self._sequence[run_id] = sequence
        event = TraderAnalysisEvent(
            run_id=run_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(),
        )
        saved = self.repository.append_event(event)
        self._emit_trace(
            run_id,
            event_type=event_type,
            stage=event_type.split(".", 1)[0],
            payload=payload,
        )
        stage_map = {
            "preflight.started": (TraderTaskStatus.PREFLIGHTING, "preflighting"),
            "graph.started": (TraderTaskStatus.RUNNING, "graph_running"),
        }
        transition = stage_map.get(event_type)
        if transition is not None:
            run = self.repository.get_run(run_id)
            if run is not None and run.task_status not in {
                TraderTaskStatus.COMPLETED,
                TraderTaskStatus.FAILED,
                TraderTaskStatus.CANCELLED,
            }:
                run.task_status, run.current_stage = transition
                self.repository.save_run(run)
        return saved

    def _emit_trace(self, run_id: str, **values: object) -> TraderAnalysisTraceEvent:
        with self._state_lock:
            sequence = self._trace_sequence.get(run_id, 0) + 1
            self._trace_sequence[run_id] = sequence
        event = TraderAnalysisTraceEvent(
            run_id=run_id,
            sequence=sequence,
            created_at=datetime.now(),
            **values,
        )
        return self.repository.append_trace(event)


def get_trader_analysis_task_service() -> TraderAnalysisTaskService:
    return TraderAnalysisTaskService.get_instance()
