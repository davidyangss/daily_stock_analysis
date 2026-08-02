from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from src.trader_analysis.config import TraderAnalysisConfig
from src.trader_analysis.trace import RoleTraceCallback, sanitize_trace
from src.trader_analysis.orchestrator import TraderAnalysisOrchestrator
from src.trader_analysis.graph_runner import TradingAgentsGraphRunner, _tradingagents_provider
from src.trader_analysis.identity.resolver import resolve_instrument
from src.trader_analysis.model_routes import ModelRoute
from src.trader_analysis.persistence.repository import TraderAnalysisRepository
from src.trader_analysis.reporting import REPORT_MODULES, render_run_markdown, reports_from_state
from src.trader_analysis.schemas.evidence import EvidenceEnvelope, EvidenceStatus
from src.trader_analysis.schemas.result import (
    TraderAnalysisEvent,
    TraderAnalysisReport,
    TraderAnalysisRun,
    TraderTaskStatus,
)
from src.trader_analysis.task_service import _hydrate_legacy_instrument_name
from src.trader_analysis.schemas.trace import TraderAnalysisTraceEvent


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


class MarketManager:
    def get_a_share_name_local_then_iwencai(self, symbol: str):
        return "贵州茅台" if symbol == "600519" else None


class MarketAdapter:
    manager = MarketManager()

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

    def fetch_sentiment(self, **kwargs):
        return envelope("sentiment", {"social_items": [{"title": "verified community opinion"}]}, EvidenceStatus.PARTIAL)


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
    assert run.instrument is not None
    assert run.instrument.name == "贵州茅台"
    assert {report.kind for report in run.reports} >= {"market", "final_decision", "data_quality"}
    assert any(event == "graph.completed" for event, _ in events)


def test_orchestrator_stops_before_evidence_when_stock_name_is_unresolved(tmp_path: Path) -> None:
    class UnknownNameManager:
        def get_a_share_name_local_then_iwencai(self, symbol: str):
            return None

    adapter = MarketAdapter()
    adapter.manager = UnknownNameManager()
    events = []

    run = TraderAnalysisOrchestrator(
        config=config(tmp_path),
        market_adapter=adapter,
        context_adapter=ContextAdapter(),
        graph_runner=GraphRunner(),
    ).run(
        run_id="run-unresolved",
        symbol="600519",
        trade_date=date(2026, 7, 31),
        emit=lambda event, payload: events.append((event, payload)),
        is_cancelled=lambda: False,
    )

    assert run.analysis_status.value == "insufficient_evidence"
    assert run.error is not None
    assert run.error.code == "instrument_name_unresolved"
    assert run.reports == []
    assert not any(event == "evidence.started" for event, _ in events)


def test_legacy_run_display_name_is_hydrated_from_local_index() -> None:
    run = TraderAnalysisRun(
        run_id="legacy-name",
        task_status=TraderTaskStatus.COMPLETED,
        symbol="603986",
        trade_date=date(2026, 7, 31),
        created_at=datetime.now(),
        current_stage="completed",
        instrument=resolve_instrument("603986", date(2026, 7, 31)),
    )

    hydrated = _hydrate_legacy_instrument_name(run)

    assert hydrated.instrument is not None
    assert hydrated.instrument.name == "兆易创新"
    assert "兆易创新（603986）" in hydrated.instrument.description


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


def test_role_trace_completion_contains_correlated_input_output_and_persists_usage(monkeypatch) -> None:
    class Response:
        llm_output = {
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
        }

        def model_dump(self, mode="json"):
            return {"generations": [[{"text": "持有"}]]}

    emitted = []
    persisted = []
    monkeypatch.setattr(
        "src.trader_analysis.trace.persist_llm_usage",
        lambda usage, model, call_type, stock_code=None: persisted.append(
            (usage, model, call_type, stock_code)
        ),
    )
    callback = RoleTraceCallback(
        role="market",
        route=SimpleNamespace(
            deployment_name="market-route", provider="openai", model="market-model",
        ),
        emit=lambda **values: emitted.append(values),
        content_limit=4096,
        stock_code="600519",
    )
    run_id = "llm-operation-1"

    callback.on_chat_model_start({}, [[{"role": "user", "content": "分析 600519"}]], run_id=run_id)
    callback.on_llm_end(Response(), run_id=run_id)

    assert emitted[0]["payload"]["operation_id"] == run_id
    completed = emitted[1]["payload"]
    assert completed["operation_id"] == run_id
    assert completed["input"]["messages"][0][0]["content"] == "分析 600519"
    assert completed["output"]["response"]["generations"][0][0]["text"] == "持有"
    assert completed["usage"] == Response.llm_output
    usage, model, call_type, stock_code = persisted[0]
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 2
    assert usage["total_tokens"] == 12
    assert (model, call_type, stock_code) == ("market-model", "trader_analysis", "600519")


def test_role_trace_does_not_persist_missing_usage(monkeypatch) -> None:
    class Response:
        llm_output = {"model_name": "market-model"}
        generations = []

        def model_dump(self, mode="json"):
            return {"generations": []}

    persisted = []
    monkeypatch.setattr(
        "src.trader_analysis.trace.persist_llm_usage",
        lambda *args, **kwargs: persisted.append((args, kwargs)),
    )
    callback = RoleTraceCallback(
        role="market",
        route=SimpleNamespace(
            deployment_name="market-route", provider="openai", model="market-model",
        ),
        emit=lambda **values: None,
        content_limit=4096,
        stock_code="600519",
    )

    callback.on_llm_end(Response(), run_id="llm-operation-without-usage")

    assert persisted == []


def test_custom_openai_gateway_uses_openai_compatible_client() -> None:
    assert _tradingagents_provider("openai", "https://gateway.example/v1") == "openai_compatible"
    assert _tradingagents_provider("openai", "https://api.openai.com/v1") == "openai"
    assert _tradingagents_provider("anthropic", "https://gateway.example/v1") == "anthropic"


def test_graph_checkpoint_signature_is_isolated_by_api_run(tmp_path: Path) -> None:
    captured = []

    class FakeGraph:
        def __init__(self, selected_analysts, debug, config, data_toolkit, role_llms):
            self.config = config
            captured.append(self)

        def _run_signature(self, asset_type: str) -> str:
            return f"asset={asset_type}"

        def propagate(self, symbol: str, trade_date: str, asset_type: str = "stock"):
            captured.append(self._run_signature(asset_type))
            return {"final_trade_decision": "HOLD"}, "HOLD"

    runner = TradingAgentsGraphRunner(config(tmp_path), graph_factory=FakeGraph)
    runner._graph_config = lambda: {"checkpoint_enabled": True}
    runner._build_role_llms = lambda trace_emit: {}
    instrument = SimpleNamespace(symbol="688825", name="688825", exchange="SH")
    toolkit = SimpleNamespace()

    runner.run(
        toolkit=toolkit,
        instrument=instrument,
        trade_date="2026-07-29",
        run_id="run-attempt-9",
    )
    runner.run(
        toolkit=toolkit,
        instrument=instrument,
        trade_date="2026-07-29",
        run_id="run-attempt-10",
    )

    signatures = [item for item in captured if isinstance(item, str)]
    assert signatures == [
        "asset=stock|dsa_run=run-attempt-9",
        "asset=stock|dsa_run=run-attempt-10",
    ]
    assert all(item.debug is True for item in captured if not isinstance(item, str))


def test_graph_requires_simplified_chinese_from_the_first_market_report_sentence(tmp_path: Path) -> None:
    captured = []

    class FakeGraph:
        def __init__(self, selected_analysts, debug, config, data_toolkit, role_llms):
            self.config = config

        def propagate(self, symbol: str, trade_date: str, asset_type: str = "stock"):
            captured.append(self.resolve_instrument_context(symbol, asset_type))
            return {"final_trade_decision": "持有"}, "持有"

    route = ModelRoute(deployment_name="fixture", provider="openai", model="fixture")
    runner = TradingAgentsGraphRunner(
        replace(config(tmp_path), model_routes={"trader": route, "portfolio_manager": route}),
        graph_factory=FakeGraph,
    )
    runner._build_role_llms = lambda trace_emit: {}
    runner.run(
        toolkit=SimpleNamespace(),
        instrument=SimpleNamespace(symbol="600519", name="贵州茅台", exchange="SH"),
        trade_date="2026-07-31",
        run_id="chinese-report",
    )

    assert runner._graph_config()["output_language"] == "Simplified Chinese"
    assert "第一句话也必须使用中文" in captured[0]
    assert "不得以 `FINAL TRANSACTION PROPOSAL`" in captured[0]
    assert "从工具返回日线的 low 列取该区间精确最小值" in captured[0]
    assert "指标值必须与所写交易日来自工具输出的同一行" in captured[0]
    assert "不得把月中或月末数据描述为月初数据" in captured[0]
    assert "上影线=high-max(open,close)" in captured[0]
    assert "当 open=high 时上影线为 0，禁止描述为长上影" in captured[0]
    assert "应描述为高开长阴或光头阴线" in captured[0]
    assert "`价格倍数` 必须写为 P/L" in captured[0]
    assert "`累计涨幅` 必须写为 (P/L-1)*100%" in captured[0]
    assert "adjustment=unknown 时必须说明复权口径未知" in captured[0]


def test_repository_relates_reports_debug_events_and_llm_trace_by_run_id(tmp_path: Path) -> None:
    repository = TraderAnalysisRepository(tmp_path)
    created_at = datetime(2026, 7, 31, 10, 0)
    repository.save_run(TraderAnalysisRun(
        run_id="linked-run",
        task_status=TraderTaskStatus.COMPLETED,
        symbol="600519",
        trade_date=date(2026, 7, 31),
        created_at=created_at,
        reports=[TraderAnalysisReport(kind="final", title="最终报告", content="持有")],
    ))
    repository.append_event(TraderAnalysisEvent(
        run_id="linked-run",
        sequence=1,
        event_type="graph.completed",
        payload={"status": "ok"},
        created_at=created_at,
    ))
    repository.append_trace(TraderAnalysisTraceEvent(
        run_id="linked-run",
        sequence=1,
        event_type="llm.completed",
        stage="trader",
        role="trader",
        deployment_name="quick-route",
        provider="openai",
        model="quick",
        payload={"response": "持有"},
        created_at=created_at,
    ))

    reloaded = TraderAnalysisRepository(tmp_path)
    run = reloaded.get_run("linked-run")
    assert run is not None
    assert run.reports[0].content == "持有"
    assert reloaded.list_events("linked-run")[0].payload == {"status": "ok"}
    assert reloaded.list_trace("linked-run")[0].payload == {"response": "持有"}

    with sqlite3.connect(tmp_path / "trader_analysis.sqlite3") as connection:
        assert connection.execute(
            "SELECT run_id FROM trader_analysis_reports WHERE run_id = 'linked-run'"
        ).fetchone() == ("linked-run",)
        assert connection.execute(
            "SELECT run_id FROM trader_analysis_events WHERE run_id = 'linked-run'"
        ).fetchone() == ("linked-run",)
        assert connection.execute(
            "SELECT run_id FROM trader_analysis_trace WHERE run_id = 'linked-run'"
        ).fetchone() == ("linked-run",)


def test_repository_serializes_temporal_trace_payload_as_iso8601(tmp_path: Path) -> None:
    repository = TraderAnalysisRepository(tmp_path)
    repository.save_run(TraderAnalysisRun(
        run_id="temporal-trace",
        task_status=TraderTaskStatus.RUNNING,
        symbol="688825",
        trade_date=date(2026, 7, 29),
        created_at=datetime(2026, 8, 1, 14, 30),
    ))
    repository.append_trace(TraderAnalysisTraceEvent(
        run_id="temporal-trace",
        sequence=1,
        event_type="evidence.consumed",
        stage="tool",
        payload={
            "capability": "market_daily_bars",
            "as_of": datetime(2026, 7, 29, 15, 0),
            "trade_date": date(2026, 7, 29),
        },
        created_at=datetime(2026, 8, 1, 14, 31),
    ))

    payload = TraderAnalysisRepository(tmp_path).list_trace("temporal-trace")[0].payload
    assert payload["as_of"] == "2026-07-29T15:00:00"
    assert payload["trade_date"] == "2026-07-29"


def test_report_modules_extract_all_public_trading_roles() -> None:
    state = {
        "market_report": "市场",
        "sentiment_report": "情绪",
        "news_report": "新闻",
        "fundamentals_report": "基本面",
        "investment_debate_state": {"bull_history": "多头", "bear_history": "空头"},
        "investment_plan": "研究决策",
        "trader_investment_plan": "交易计划",
        "risk_debate_state": {
            "aggressive_history": "激进",
            "conservative_history": "保守",
            "neutral_history": "中性",
            "judge_decision": "组合经理",
        },
        "final_trade_decision": "最终决策",
    }

    reports = reports_from_state(state)

    assert [report.kind for report in reports] == [kind for kind, _title in REPORT_MODULES]
    assert all(report.title[0] in "📈💭📰💰🐂🐻🔬💼⚡🛡⚖👔🎯📋" for report in reports)


def test_market_report_localizes_upstream_english_proposal_prefix() -> None:
    reports = reports_from_state({
        "market_report": "FINAL TRANSACTION PROPOSAL: **HOLD**\n趋势保持震荡。",
    })

    assert reports[0].content == "最终交易建议：持有\n\n趋势保持震荡。"


def test_markdown_export_uses_chinese_headings_and_persisted_content() -> None:
    run = TraderAnalysisRun(
        run_id="markdown-run",
        task_status=TraderTaskStatus.COMPLETED,
        analysis_status="degraded",
        symbol="688825",
        trade_date=date(2026, 7, 29),
        created_at=datetime(2026, 8, 1, 10, 0),
        completed_at=datetime(2026, 8, 1, 10, 5),
        reports=reports_from_state({
            "market_report": "市场正文",
            "final_trade_decision": "最终正文",
        }),
    )

    markdown = render_run_markdown(run)

    assert markdown.startswith("# 名称未核验（688825）交易员分析报告")
    assert "- 分析状态：降级可用" in markdown
    assert "## 📈 市场技术分析\n\n市场正文" in markdown
    assert "## 🎯 最终交易决策\n\n最终正文" in markdown
    assert "不构成投资建议" in markdown


def test_repository_lists_durable_runs_newest_first_and_filters_status(tmp_path: Path) -> None:
    repository = TraderAnalysisRepository(tmp_path)
    repository.save_run(TraderAnalysisRun(
        run_id="older",
        task_status=TraderTaskStatus.COMPLETED,
        symbol="600519",
        trade_date=date(2026, 7, 30),
        created_at=datetime(2026, 7, 30, 10, 0),
    ))
    repository.save_run(TraderAnalysisRun(
        run_id="newer",
        task_status=TraderTaskStatus.RUNNING,
        symbol="000001",
        trade_date=date(2026, 7, 31),
        created_at=datetime(2026, 7, 31, 10, 0),
    ))

    reloaded = TraderAnalysisRepository(tmp_path)

    assert [run.run_id for run in reloaded.list_runs()] == ["newer", "older"]
    assert [run.run_id for run in reloaded.list_runs(statuses=["completed"])] == ["older"]


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


def test_config_maps_bounded_browser_reader_settings(tmp_path: Path) -> None:
    app_config = SimpleNamespace(
        trader_analysis_enabled=True,
        trader_analysis_results_dir=str(tmp_path),
        trader_analysis_checkpoint_db=str(tmp_path / "checkpoint.sqlite"),
        trader_analysis_browser_reader_enabled=True,
        trader_analysis_browser_reader_command="/opt/bin/agent-browser",
        trader_analysis_browser_reader_max_pages=2,
        trader_analysis_browser_reader_timeout_seconds=15,
        trader_analysis_browser_reader_max_chars=8000,
        trader_analysis_browser_reader_allowed_domains=["xueqiu.com", "sse.com.cn"],
    )

    mapped = TraderAnalysisConfig.from_app_config(app_config)

    assert mapped.browser_reader_enabled is True
    assert mapped.browser_reader_command == "/opt/bin/agent-browser"
    assert mapped.browser_reader_max_pages == 2
    assert mapped.browser_reader_timeout_seconds == 15
    assert mapped.browser_reader_max_chars == 8000
    assert mapped.browser_reader_allowed_domains == ("xueqiu.com", "sse.com.cn")


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
