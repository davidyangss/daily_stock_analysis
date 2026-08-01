"""SQLite-backed persistence for trader-analysis runs and related artifacts."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from src.trader_analysis.schemas.result import TraderAnalysisEvent, TraderAnalysisRun
from src.trader_analysis.schemas.trace import TraderAnalysisTraceEvent


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trader_analysis_runs (
    run_id TEXT PRIMARY KEY,
    task_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trader_analysis_runs_created
    ON trader_analysis_runs(created_at DESC, run_id DESC);
CREATE INDEX IF NOT EXISTS idx_trader_analysis_runs_status_created
    ON trader_analysis_runs(task_status, created_at DESC, run_id DESC);

CREATE TABLE IF NOT EXISTS trader_analysis_reports (
    run_id TEXT NOT NULL,
    report_index INTEGER NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (run_id, report_index),
    FOREIGN KEY (run_id) REFERENCES trader_analysis_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trader_analysis_events (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence),
    FOREIGN KEY (run_id) REFERENCES trader_analysis_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trader_analysis_trace (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    stage TEXT NOT NULL,
    role TEXT,
    deployment_name TEXT,
    provider TEXT,
    model TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence),
    FOREIGN KEY (run_id) REFERENCES trader_analysis_runs(run_id) ON DELETE CASCADE
);
"""


class TraderAnalysisRepository:
    """Persist runs, reports, debug events and sanitized LLM traces by run ID."""

    def __init__(self, results_dir: Optional[Path] = None) -> None:
        self._runs: Dict[str, TraderAnalysisRun] = {}
        self._events: Dict[str, List[TraderAnalysisEvent]] = {}
        self._traces: Dict[str, List[TraderAnalysisTraceEvent]] = {}
        self._results_dir: Optional[Path] = None
        self._db_path: Optional[Path] = None
        self._lock = threading.RLock()
        if results_dir is not None:
            self.configure(results_dir)

    def configure(self, results_dir: Path) -> None:
        with self._lock:
            resolved = results_dir.resolve()
            if self._results_dir is not None and self._results_dir != resolved and self._runs:
                raise RuntimeError("trader-analysis results directory cannot change while tasks exist")
            self._results_dir = resolved
            self._db_path = resolved / "trader_analysis.sqlite3"
            resolved.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(_SCHEMA)

    def save_run(self, run: TraderAnalysisRun) -> TraderAnalysisRun:
        with self._lock:
            snapshot = run.model_copy(deep=True)
            self._runs[run.run_id] = snapshot
            if self._db_path is not None:
                with self._connect() as connection:
                    connection.execute(
                        """INSERT INTO trader_analysis_runs(run_id, task_status, created_at, payload_json)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(run_id) DO UPDATE SET
                               task_status=excluded.task_status,
                               created_at=excluded.created_at,
                               payload_json=excluded.payload_json""",
                        (
                            run.run_id,
                            run.task_status.value,
                            run.created_at.isoformat(),
                            self._json(snapshot.model_dump(mode="json")),
                        ),
                    )
                    connection.execute("DELETE FROM trader_analysis_reports WHERE run_id = ?", (run.run_id,))
                    connection.executemany(
                        """INSERT INTO trader_analysis_reports
                           (run_id, report_index, kind, title, content) VALUES (?, ?, ?, ?, ?)""",
                        [
                            (run.run_id, index, report.kind, report.title, report.content)
                            for index, report in enumerate(snapshot.reports)
                        ],
                    )
            self._write(run.run_id, "run.json", snapshot.model_dump(mode="json"))
            return snapshot.model_copy(deep=True)

    def get_run(self, run_id: str) -> Optional[TraderAnalysisRun]:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None and self._db_path is not None:
                with self._connect() as connection:
                    row = connection.execute(
                        "SELECT payload_json FROM trader_analysis_runs WHERE run_id = ?", (run_id,)
                    ).fetchone()
                if row is not None:
                    run = TraderAnalysisRun.model_validate(json.loads(row["payload_json"]))
                    self._runs[run_id] = run
            if run is None:
                payload = self._read(run_id, "run.json")
                if payload is not None:
                    run = TraderAnalysisRun.model_validate(payload)
                    self.save_run(run)
            return run.model_copy(deep=True) if run else None

    def list_runs(
        self,
        *,
        statuses: Optional[Sequence[str]] = None,
        offset: int = 0,
        limit: int = 100,
    ) -> List[TraderAnalysisRun]:
        """Return durable runs newest-first, importing legacy JSON runs on demand."""
        with self._lock:
            self._import_legacy_runs()
            if self._db_path is None:
                allowed = set(statuses or [])
                runs = [
                    run.model_copy(deep=True)
                    for run in self._runs.values()
                    if not allowed or run.task_status.value in allowed
                ]
                runs.sort(key=lambda run: (run.created_at, run.run_id), reverse=True)
                return runs[offset:offset + limit]

            parameters: list[object] = []
            where = ""
            if statuses:
                placeholders = ",".join("?" for _ in statuses)
                where = f"WHERE task_status IN ({placeholders})"
                parameters.extend(statuses)
            parameters.extend((limit, offset))
            with self._connect() as connection:
                rows = connection.execute(
                    f"""SELECT payload_json FROM trader_analysis_runs {where}
                        ORDER BY created_at DESC, run_id DESC LIMIT ? OFFSET ?""",
                    parameters,
                ).fetchall()
            runs = [TraderAnalysisRun.model_validate(json.loads(row["payload_json"])) for row in rows]
            for run in runs:
                self._runs[run.run_id] = run
            return [run.model_copy(deep=True) for run in runs]

    def append_event(self, event: TraderAnalysisEvent) -> TraderAnalysisEvent:
        with self._lock:
            snapshot = event.model_copy(deep=True)
            events = self._load_events(event.run_id)
            events = [item for item in events if item.sequence != event.sequence]
            events.append(snapshot)
            events.sort(key=lambda item: item.sequence)
            self._events[event.run_id] = events
            if self._db_path is not None:
                with self._connect() as connection:
                    connection.execute(
                        """INSERT OR REPLACE INTO trader_analysis_events
                           (run_id, sequence, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)""",
                        (event.run_id, event.sequence, event.event_type, self._json(event.payload), event.created_at.isoformat()),
                    )
            self._write(event.run_id, "events.json", [item.model_dump(mode="json") for item in events])
            return snapshot.model_copy(deep=True)

    def list_events(self, run_id: str, after: int = 0) -> List[TraderAnalysisEvent]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._load_events(run_id) if item.sequence > after]

    def append_trace(self, event: TraderAnalysisTraceEvent) -> TraderAnalysisTraceEvent:
        with self._lock:
            snapshot = event.model_copy(deep=True)
            traces = self._load_trace(event.run_id)
            traces = [item for item in traces if item.sequence != event.sequence]
            traces.append(snapshot)
            traces.sort(key=lambda item: item.sequence)
            self._traces[event.run_id] = traces
            if self._db_path is not None:
                with self._connect() as connection:
                    connection.execute(
                        """INSERT OR REPLACE INTO trader_analysis_trace
                           (run_id, sequence, event_type, stage, role, deployment_name, provider, model,
                            payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            event.run_id, event.sequence, event.event_type, event.stage, event.role,
                            event.deployment_name, event.provider, event.model, self._json(event.payload),
                            event.created_at.isoformat(),
                        ),
                    )
            self._write(event.run_id, "trace.json", [item.model_dump(mode="json") for item in traces])
            return snapshot.model_copy(deep=True)

    def list_trace(self, run_id: str, after: int = 0) -> List[TraderAnalysisTraceEvent]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._load_trace(run_id) if item.sequence > after]

    def _load_events(self, run_id: str) -> List[TraderAnalysisEvent]:
        if run_id in self._events:
            return self._events[run_id]
        events: List[TraderAnalysisEvent] = []
        if self._db_path is not None:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT sequence, event_type, payload_json, created_at
                       FROM trader_analysis_events WHERE run_id = ? ORDER BY sequence""",
                    (run_id,),
                ).fetchall()
            events = [TraderAnalysisEvent(
                run_id=run_id,
                sequence=row["sequence"],
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
            ) for row in rows]
        if not events:
            payload = self._read(run_id, "events.json") or []
            events = [TraderAnalysisEvent.model_validate(item) for item in payload]
            if events and self.get_run(run_id) is not None:
                for event in events:
                    self._insert_legacy_event(event)
        self._events[run_id] = events
        return events

    def _load_trace(self, run_id: str) -> List[TraderAnalysisTraceEvent]:
        if run_id in self._traces:
            return self._traces[run_id]
        traces: List[TraderAnalysisTraceEvent] = []
        if self._db_path is not None:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM trader_analysis_trace WHERE run_id = ? ORDER BY sequence", (run_id,)
                ).fetchall()
            traces = [TraderAnalysisTraceEvent(
                run_id=run_id,
                sequence=row["sequence"],
                event_type=row["event_type"],
                stage=row["stage"],
                role=row["role"],
                deployment_name=row["deployment_name"],
                provider=row["provider"],
                model=row["model"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
            ) for row in rows]
        if not traces:
            payload = self._read(run_id, "trace.json") or []
            traces = [TraderAnalysisTraceEvent.model_validate(item) for item in payload]
            if traces and self.get_run(run_id) is not None:
                for event in traces:
                    self._insert_legacy_trace(event)
        self._traces[run_id] = traces
        return traces

    def _import_legacy_runs(self) -> None:
        if self._results_dir is None:
            return
        runs_directory = self._results_dir / "runs"
        if not runs_directory.is_dir():
            return
        for directory in runs_directory.iterdir():
            if not directory.is_dir():
                continue
            if self._db_has_run(directory.name):
                continue
            payload = self._read(directory.name, "run.json")
            if payload is not None:
                self.save_run(TraderAnalysisRun.model_validate(payload))

    def _insert_legacy_event(self, event: TraderAnalysisEvent) -> None:
        if self._db_path is None:
            return
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO trader_analysis_events
                   (run_id, sequence, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)""",
                (event.run_id, event.sequence, event.event_type, self._json(event.payload), event.created_at.isoformat()),
            )

    def _insert_legacy_trace(self, event: TraderAnalysisTraceEvent) -> None:
        if self._db_path is None:
            return
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO trader_analysis_trace
                   (run_id, sequence, event_type, stage, role, deployment_name, provider, model,
                    payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.run_id, event.sequence, event.event_type, event.stage, event.role,
                    event.deployment_name, event.provider, event.model, self._json(event.payload),
                    event.created_at.isoformat(),
                ),
            )

    def _db_has_run(self, run_id: str) -> bool:
        if self._db_path is None:
            return False
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM trader_analysis_runs WHERE run_id = ?", (run_id,)
            ).fetchone() is not None

    def _connect(self) -> sqlite3.Connection:
        if self._db_path is None:
            raise RuntimeError("trader-analysis repository is not configured")
        connection = sqlite3.connect(self._db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    @staticmethod
    def _json(payload: object) -> str:
        def encode_temporal(value: object) -> str:
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=encode_temporal,
        )

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
