"""Independent trader-analysis orchestration."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Callable, Optional

from src.trader_analysis.adapters.market import MarketEvidenceAdapter
from src.trader_analysis.adapters.context import ContextEvidenceAdapter
from src.trader_analysis.config import TraderAnalysisConfig
from src.trader_analysis.errors import build_error
from src.trader_analysis.evidence.ledger import create_ledger
from src.trader_analysis.evidence.policy import evaluate_overall_status
from src.trader_analysis.evidence.renderer import render_quality_summary
from src.trader_analysis.identity.resolver import UnsupportedInstrumentError, resolve_instrument
from src.trader_analysis.schemas.result import (
    TraderAnalysisReport,
    TraderAnalysisRun,
    TraderAnalysisStatus,
    TraderTaskStatus,
)
from src.trader_analysis.graph_runner import (
    REPORT_FIELDS,
    TradingAgentsConfigurationError,
    TradingAgentsCancelledError,
    TradingAgentsGraphRunner,
)
from src.trader_analysis.toolkit import DsaTradingAgentsToolkit


EventSink = Callable[[str, dict], None]


class TraderAnalysisOrchestrator:
    def __init__(
        self,
        *,
        config: TraderAnalysisConfig,
        market_adapter: Optional[MarketEvidenceAdapter] = None,
        context_adapter: Optional[ContextEvidenceAdapter] = None,
        graph_runner: Optional[TradingAgentsGraphRunner] = None,
    ) -> None:
        self.config = config
        self.market_adapter = market_adapter or MarketEvidenceAdapter()
        self.context_adapter = context_adapter or ContextEvidenceAdapter(self.market_adapter.manager)
        self.graph_runner = graph_runner or TradingAgentsGraphRunner(config)

    def run(
        self,
        *,
        run_id: str,
        symbol: str,
        trade_date: date,
        emit: EventSink,
        is_cancelled: Callable[[], bool],
        trace_emit: Optional[Callable[..., None]] = None,
    ) -> TraderAnalysisRun:
        created_at = datetime.now()
        run = TraderAnalysisRun(
            run_id=run_id,
            task_status=TraderTaskStatus.PREFLIGHTING,
            symbol=symbol,
            trade_date=trade_date,
            created_at=created_at,
            started_at=created_at,
            current_stage="preflighting",
            metadata={
                "tradingagents_version": self.config.tradingagents_version,
                "tradingagents_commit": self.config.tradingagents_commit,
                "data_toolkit_version": self.config.data_toolkit_version,
                "evidence_policy_version": self.config.evidence_policy_version,
            },
        )
        emit("preflight.started", {"symbol": symbol, "trade_date": trade_date.isoformat()})

        if not self.config.enabled:
            run.task_status = TraderTaskStatus.COMPLETED
            run.analysis_status = TraderAnalysisStatus.INSUFFICIENT_EVIDENCE
            run.current_stage = "completed"
            run.completed_at = datetime.now()
            run.error = build_error(
                code="configuration_error",
                message="交易员分析功能未启用；请设置 TRADER_ANALYSIS_ENABLED=true 后再提交运行",
                stage="preflight",
                run_id=run_id,
                retriable=True,
            )
            emit("preflight.completed", {"analysis_status": run.analysis_status.value})
            emit("run.completed", {"analysis_status": run.analysis_status.value})
            return run

        if trade_date > date.today():
            run.task_status = TraderTaskStatus.COMPLETED
            run.analysis_status = TraderAnalysisStatus.INSUFFICIENT_EVIDENCE
            run.current_stage = "completed"
            run.completed_at = datetime.now()
            run.error = build_error(
                code="invalid_request",
                message="分析日期不能晚于当前日期",
                stage="preflight",
                run_id=run_id,
            )
            emit("preflight.completed", {"analysis_status": run.analysis_status.value})
            emit("run.completed", {"analysis_status": run.analysis_status.value})
            return run

        try:
            instrument = resolve_instrument(symbol, trade_date)
        except UnsupportedInstrumentError as exc:
            run.task_status = TraderTaskStatus.COMPLETED
            run.analysis_status = TraderAnalysisStatus.INSUFFICIENT_EVIDENCE
            run.current_stage = "completed"
            run.completed_at = datetime.now()
            run.error = build_error(
                code="unsupported_instrument",
                message=str(exc),
                stage="preflight",
                run_id=run_id,
            )
            emit("preflight.completed", {"analysis_status": run.analysis_status.value})
            emit("run.completed", {"analysis_status": run.analysis_status.value})
            return run

        if is_cancelled():
            run.task_status = TraderTaskStatus.CANCELLED
            run.current_stage = "cancelled"
            run.completed_at = datetime.now()
            emit("run.cancelled", {})
            return run

        run.symbol = instrument.symbol
        run.instrument = instrument
        ledger = create_ledger(run_id, instrument.symbol, trade_date)

        daily = self.market_adapter.fetch_daily_bars(
            run_id=run_id,
            symbol=instrument.symbol,
            trade_date=trade_date,
            min_daily_bars=self.config.min_daily_bars,
        )
        ledger.add(daily)
        emit("quality.updated", {"capability": daily.capability, "status": daily.status.value})

        snapshot = self.market_adapter.fetch_snapshot(
            run_id=run_id,
            symbol=instrument.symbol,
            trade_date=trade_date,
            daily_envelope=daily,
        )
        ledger.add(snapshot)
        emit("quality.updated", {"capability": snapshot.capability, "status": snapshot.status.value})

        fundamentals = self.context_adapter.fetch_fundamentals(
            run_id=run_id,
            symbol=instrument.symbol,
            trade_date=trade_date,
            timeout=self.config.provider_timeout_seconds,
        )
        ledger.add(fundamentals)
        emit("quality.updated", {"capability": fundamentals.capability, "status": fundamentals.status.value})

        news = self.context_adapter.fetch_news(
            run_id=run_id,
            symbol=instrument.symbol,
            name=instrument.name,
            trade_date=trade_date,
        )
        ledger.add(news)
        emit("quality.updated", {"capability": news.capability, "status": news.status.value})

        sentiment = self.context_adapter.build_sentiment(
            run_id=run_id,
            symbol=instrument.symbol,
            trade_date=trade_date,
            news=news,
        )
        ledger.add(sentiment)
        emit("quality.updated", {"capability": sentiment.capability, "status": sentiment.status.value})

        ledger.overall_status = evaluate_overall_status(ledger)  # type: ignore[assignment]
        run.quality.overall_status = ledger.overall_status
        run.quality.providers_used = ledger.providers_used
        run.quality.warnings = ledger.warnings
        run.quality.blocking_issues = ledger.blocking_issues

        emit("preflight.completed", {"analysis_status": ledger.overall_status})

        if ledger.overall_status == "insufficient_evidence":
            run.task_status = TraderTaskStatus.COMPLETED
            run.analysis_status = TraderAnalysisStatus.INSUFFICIENT_EVIDENCE
            run.current_stage = "completed"
            run.completed_at = datetime.now()
            run.reports.append(TraderAnalysisReport(
                kind="data_quality",
                title="数据质量与分析限制",
                content=render_quality_summary(ledger),
            ))
            emit("report.written", {"kind": "data_quality"})
            emit("run.completed", {"analysis_status": run.analysis_status.value})
            return run

        run.task_status = TraderTaskStatus.RUNNING
        run.current_stage = "graph_running"
        emit("graph.started", {"analysts": ["market", "social", "news", "fundamentals"]})
        try:
            state, decision = self.graph_runner.run(
                toolkit=DsaTradingAgentsToolkit(ledger, trace_emit=trace_emit),
                instrument=instrument,
                trade_date=trade_date.isoformat(),
                is_cancelled=is_cancelled,
                trace_emit=trace_emit,
            )
        except TradingAgentsCancelledError:
            run.task_status = TraderTaskStatus.CANCELLED
            run.current_stage = "cancelled"
            run.completed_at = datetime.now()
            emit("run.cancelled", {})
            return run
        except TradingAgentsConfigurationError as exc:
            return self._failed(run, ledger, emit, "configuration_error", str(exc), "graph_configuration")
        except Exception as exc:
            return self._failed(
                run, ledger, emit, "graph_execution_failed",
                "TradingAgents 多角色分析执行失败", "graph_execution",
                details={"error_type": type(exc).__name__},
            )

        if is_cancelled():
            run.task_status = TraderTaskStatus.CANCELLED
            run.current_stage = "cancelled"
            run.completed_at = datetime.now()
            emit("run.cancelled", {})
            return run

        for field, kind, title in REPORT_FIELDS:
            content = str(state.get(field) or "").strip()
            if content:
                run.reports.append(TraderAnalysisReport(kind=kind, title=title, content=content))
                emit("report.written", {"kind": kind})
        run.reports.append(TraderAnalysisReport(
            kind="data_quality",
            title="数据质量与分析限制",
            content=render_quality_summary(ledger),
        ))
        run.task_status = TraderTaskStatus.COMPLETED
        run.analysis_status = (
            TraderAnalysisStatus.COMPLETE
            if ledger.overall_status == "complete"
            else TraderAnalysisStatus.DEGRADED
        )
        run.current_stage = "completed"
        run.completed_at = datetime.now()
        emit("graph.completed", {"decision": decision})
        emit("run.completed", {"analysis_status": run.analysis_status.value})
        return run

    def _failed(
        self,
        run: TraderAnalysisRun,
        ledger: object,
        emit: EventSink,
        code: str,
        message: str,
        stage: str,
        *,
        details: Optional[dict] = None,
    ) -> TraderAnalysisRun:
        run.task_status = TraderTaskStatus.FAILED
        run.current_stage = "failed"
        run.completed_at = datetime.now()
        run.error = build_error(
            code=code,
            message=message,
            stage=stage,
            run_id=run.run_id,
            retriable=code == "graph_execution_failed",
            details=details or {
                "required_version": self.config.tradingagents_version,
                "required_commit": self.config.tradingagents_commit,
                "data_toolkit_version": self.config.data_toolkit_version,
            },
        )
        run.reports.append(TraderAnalysisReport(
            kind="data_quality",
            title="数据质量与分析限制",
            content=render_quality_summary(ledger),  # type: ignore[arg-type]
        ))
        emit("run.failed", {"code": run.error.code, "trace_id": run.error.trace_id})
        return run


def new_run_id() -> str:
    return uuid.uuid4().hex
