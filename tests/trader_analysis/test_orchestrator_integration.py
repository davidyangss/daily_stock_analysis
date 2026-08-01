from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from src.trader_analysis.config import TraderAnalysisConfig
from src.trader_analysis.trace import sanitize_trace
from src.trader_analysis.orchestrator import TraderAnalysisOrchestrator
from src.trader_analysis.persistence.repository import TraderAnalysisRepository
from src.trader_analysis.schemas.evidence import EvidenceEnvelope, EvidenceStatus
from src.trader_analysis.schemas.result import TraderAnalysisRun, TraderTaskStatus


def config(tmp_path: Path) -> TraderAnalysisConfig:
    return TraderAnalysisConfig(
        enabled=True,
        max_concurrency=1,
        queue_limit=2,
        task_timeout_seconds=60,
        provider_timeout_seconds=3,
        results_dir=tmp_path,
        checkpoint_db=tmp_path / "checkpoints.sqlite",
        min_daily_bars=30,
        stale_threshold_seconds=86400,
        tradingagents_version="0.3.1",
        tradingagents_commit="test",
        llm_provider="openai",
        quick_model="quick",
        deep_model="deep",
        llm_backend_url="",
    )


def envelope(capability: str, payload: dict, status: EvidenceStatus = EvidenceStatus.OK) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        evidence_id=capability,
        run_id="run-1",
        capability=capability,
        symbol="600519",
        trade_date=date(2026, 7, 31),
        fetched_at=datetime.now(),
        status=status,
        provider="fixture",
        source_chain=["fixture"],
        payload=payload,
    )


class MarketAdapter:
    manager = object()

    def fetch_daily_bars(self, **kwargs):
        return envelope("market_daily_bars", {"rows": [{
            "trade_date": "2026-07-31", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10,
        }]})

    def fetch_snapshot(self, **kwargs):
        return envelope("verified_market_snapshot", {"last_price": 2})


class ContextAdapter:
    def fetch_fundamentals(self, **kwargs):
        return envelope("fundamentals", {"valuation": {"data": {"pe": 10}}})

    def fetch_news(self, **kwargs):
        return envelope("news", {"items": [{"title": "verified"}]})

    def build_sentiment(self, **kwargs):
        return envelope("sentiment", {"news_items": [{"title": "verified"}]}, EvidenceStatus.PARTIAL)


class GraphRunner:
    def run(self, **kwargs):
        return ({
            "market_report": "market",
            "sentiment_report": "sentiment",
            "news_report": "news",
            "fundamentals_report": "fundamentals",
            "investment_plan": "research",
            "trader_investment_plan": "trader",
            "final_trade_decision": "HOLD",
        }, "HOLD")


def test_orchestrator_executes_graph_after_complete_preflight(tmp_path: Path) -> None:
    events = []
    run = TraderAnalysisOrchestrator(
        config=config(tmp_path),
        market_adapter=MarketAdapter(),
        context_adapter=ContextAdapter(),
        graph_runner=GraphRunner(),
    ).run(
        run_id="run-1",
        symbol="600519",
        trade_date=date(2026, 7, 31),
        emit=lambda event, payload: events.append((event, payload)),
        is_cancelled=lambda: False,
    )

    assert run.task_status == TraderTaskStatus.COMPLETED
    assert run.analysis_status.value == "complete"
    assert {report.kind for report in run.reports} >= {"market", "final_decision", "data_quality"}
    assert any(event == "graph.completed" for event, _ in events)


def test_repository_round_trips_runs_and_events(tmp_path: Path) -> None:
    repository = TraderAnalysisRepository(tmp_path)
    run = TraderAnalysisRun(
        run_id="durable",
        task_status=TraderTaskStatus.PENDING,
        symbol="600519",
        trade_date=date(2026, 7, 31),
        created_at=datetime.now(),
    )
    repository.save_run(run)
    reloaded = TraderAnalysisRepository(tmp_path).get_run("durable")
    assert reloaded is not None
    assert reloaded.symbol == "600519"


def test_config_maps_existing_dsa_litellm_route_without_model_hardcoding(tmp_path: Path) -> None:
    app_config = SimpleNamespace(
        trader_analysis_enabled=True,
        trader_analysis_results_dir=str(tmp_path),
        trader_analysis_checkpoint_db=str(tmp_path / "checkpoint.sqlite"),
        agent_litellm_model="openai/quick-model",
        litellm_model="openai/deep-model",
        llm_model_list=[{
            "model_name": "openai/quick-model",
            "litellm_params": {"api_base": "https://gateway.example/v1"},
        }],
    )

    mapped = TraderAnalysisConfig.from_app_config(app_config)

    assert mapped.llm_provider == "openai"
    assert mapped.quick_model == "quick-model"
    assert mapped.deep_model == "deep-model"
    assert mapped.llm_backend_url == "https://gateway.example/v1"


def test_config_resolves_independent_role_deployments(tmp_path: Path) -> None:
    app_config = SimpleNamespace(
        trader_analysis_enabled=True,
        trader_analysis_results_dir=str(tmp_path),
        trader_analysis_checkpoint_db=str(tmp_path / "checkpoint.sqlite"),
        trader_analysis_quick_model="quick-route",
        trader_analysis_deep_model="deep-route",
        trader_analysis_model_market="market-route",
        llm_model_list=[
            {"model_name": "quick-route", "litellm_params": {"model": "openai/gpt-fast", "api_key": "secret"}},
            {"model_name": "deep-route", "litellm_params": {"model": "anthropic/claude-deep"}},
            {"model_name": "market-route", "litellm_params": {"model": "gemini/gemini-market"}},
        ],
    )

    mapped = TraderAnalysisConfig.from_app_config(app_config)

    assert mapped.model_routes["market"].provider == "google"
    assert mapped.model_routes["research_manager"].deployment_name == "deep-route"
    assert mapped.model_routes["trader"].deployment_name == "quick-route"
    assert "api_key" not in mapped.model_routes["trader"].public_dict()


def test_trace_sanitizes_secrets_and_truncates_content() -> None:
    sanitized = sanitize_trace({"authorization": "Bearer hidden", "nested": {"api-key": "hidden"}, "text": "long trace content " * 5}, limit=20)
    assert sanitized["authorization"] == "<redacted>"
    assert sanitized["nested"]["api-key"] == "<redacted>"
    assert sanitized["text"].endswith("...<truncated>")
