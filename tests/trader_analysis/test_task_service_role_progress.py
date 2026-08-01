from datetime import date, datetime

from src.trader_analysis.persistence.repository import TraderAnalysisRepository
from src.trader_analysis.schemas.result import TraderAnalysisRun, TraderTaskStatus
from src.trader_analysis.task_service import TraderAnalysisTaskService


def test_trace_events_persist_role_progress_on_run_summary() -> None:
    repository = TraderAnalysisRepository()
    service = TraderAnalysisTaskService(repository=repository)
    repository.save_run(TraderAnalysisRun(
        run_id="role-progress-run",
        task_status=TraderTaskStatus.RUNNING,
        symbol="600519",
        trade_date=date(2026, 8, 1),
        created_at=datetime(2026, 8, 1, 9, 30),
    ))

    service._emit_trace(
        "role-progress-run",
        event_type="llm.started",
        stage="market",
        role="market",
        payload={},
    )
    assert repository.get_run("role-progress-run").metadata["role_progress"] == {"market": "running"}

    service._emit_trace(
        "role-progress-run",
        event_type="llm.completed",
        stage="market",
        role="market",
        payload={},
    )
    assert repository.get_run("role-progress-run").metadata["role_progress"] == {"market": "completed"}
