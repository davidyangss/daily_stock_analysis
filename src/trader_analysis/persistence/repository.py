"""Independent durable JSON persistence for trader-analysis runs and events."""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from src.trader_analysis.schemas.result import TraderAnalysisEvent, TraderAnalysisRun
from src.trader_analysis.schemas.trace import TraderAnalysisTraceEvent


class TraderAnalysisRepository:
    def __init__(self, results_dir: Optional[Path] = None) -> None:
        self._runs: Dict[str, TraderAnalysisRun] = {}
        self._events: Dict[str, List[TraderAnalysisEvent]] = {}
        self._traces: Dict[str, List[TraderAnalysisTraceEvent]] = {}
        self._results_dir = results_dir
        self._lock = threading.RLock()

    def configure(self, results_dir: Path) -> None:
        with self._lock:
            resolved = results_dir.resolve()
            if self._results_dir is not None and self._results_dir.resolve() != resolved and self._runs:
                raise RuntimeError("trader-analysis results directory cannot change while tasks exist")
            self._results_dir = resolved
            resolved.mkdir(parents=True, exist_ok=True)

    def save_run(self, run: TraderAnalysisRun) -> TraderAnalysisRun:
        with self._lock:
            snapshot = run.model_copy(deep=True)
            self._runs[run.run_id] = snapshot
            self._write(run.run_id, "run.json", snapshot.model_dump(mode="json"))
            return snapshot.model_copy(deep=True)

    def get_run(self, run_id: str) -> Optional[TraderAnalysisRun]:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                payload = self._read(run_id, "run.json")
                if payload is not None:
                    run = TraderAnalysisRun.model_validate(payload)
                    self._runs[run_id] = run
            return run.model_copy(deep=True) if run else None

    def list_runs(
        self,
        *,
        statuses: Optional[Sequence[str]] = None,
        offset: int = 0,
        limit: int = 100,
    ) -> List[TraderAnalysisRun]:
        """Return durable runs newest-first, including runs from earlier processes."""
        with self._lock:
            if self._results_dir is not None:
                runs_directory = self._results_dir / "runs"
                if runs_directory.is_dir():
                    for directory in runs_directory.iterdir():
                        if not directory.is_dir() or directory.name in self._runs:
                            continue
                        payload = self._read(directory.name, "run.json")
                        if payload is not None:
                            run = TraderAnalysisRun.model_validate(payload)
                            self._runs[run.run_id] = run

            allowed = set(statuses or [])
            runs = [
                run.model_copy(deep=True)
                for run in self._runs.values()
                if not allowed or run.task_status.value in allowed
            ]
            runs.sort(key=lambda run: (run.created_at, run.run_id), reverse=True)
            return runs[offset:offset + limit]

    def append_event(self, event: TraderAnalysisEvent) -> TraderAnalysisEvent:
        with self._lock:
            snapshot = event.model_copy(deep=True)
            self._events.setdefault(event.run_id, []).append(snapshot)
            self._write(
                event.run_id,
                "events.json",
                [item.model_dump(mode="json") for item in self._events[event.run_id]],
            )
            return snapshot.model_copy(deep=True)

    def list_events(self, run_id: str, after: int = 0) -> List[TraderAnalysisEvent]:
        with self._lock:
            if run_id not in self._events:
                payload = self._read(run_id, "events.json") or []
                self._events[run_id] = [TraderAnalysisEvent.model_validate(item) for item in payload]
            return [item.model_copy(deep=True) for item in self._events[run_id] if item.sequence > after]

    def append_trace(self, event: TraderAnalysisTraceEvent) -> TraderAnalysisTraceEvent:
        with self._lock:
            snapshot = event.model_copy(deep=True)
            self._traces.setdefault(event.run_id, []).append(snapshot)
            self._write(event.run_id, "trace.json", [item.model_dump(mode="json") for item in self._traces[event.run_id]])
            return snapshot.model_copy(deep=True)

    def list_trace(self, run_id: str, after: int = 0) -> List[TraderAnalysisTraceEvent]:
        with self._lock:
            if run_id not in self._traces:
                payload = self._read(run_id, "trace.json") or []
                self._traces[run_id] = [TraderAnalysisTraceEvent.model_validate(item) for item in payload]
            return [item.model_copy(deep=True) for item in self._traces[run_id] if item.sequence > after]

    def _write(self, run_id: str, name: str, payload: object) -> None:
        if self._results_dir is None:
            return
        directory = self._results_dir / "runs" / run_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        temporary = directory / f".{name}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)

    def _read(self, run_id: str, name: str) -> Optional[object]:
        if self._results_dir is None:
            return None
        target = self._results_dir / "runs" / run_id / name
        if not target.is_file():
            return None
        return json.loads(target.read_text(encoding="utf-8"))


_REPOSITORY = TraderAnalysisRepository()


def get_trader_analysis_repository() -> TraderAnalysisRepository:
    return _REPOSITORY
