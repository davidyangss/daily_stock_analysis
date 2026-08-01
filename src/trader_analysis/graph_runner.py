"""Strict integration boundary for the patched upstream TradingAgents graph."""

from __future__ import annotations

import importlib.metadata
import inspect
from typing import Any, Callable, Optional

from src.trader_analysis.config import TraderAnalysisConfig
from src.trader_analysis.schemas.instrument import InstrumentContext
from src.trader_analysis.toolkit import DsaTradingAgentsToolkit


class TradingAgentsConfigurationError(RuntimeError):
    pass


class TradingAgentsCancelledError(RuntimeError):
    pass


class TradingAgentsGraphRunner:
    def __init__(self, config: TraderAnalysisConfig, graph_factory: Optional[Callable[..., Any]] = None) -> None:
        self.config = config
        self.graph_factory = graph_factory

    def run(
        self,
        *,
        toolkit: DsaTradingAgentsToolkit,
        instrument: InstrumentContext,
        trade_date: str,
        is_cancelled: Callable[[], bool] = lambda: False,
        trace_emit: Optional[Callable[..., None]] = None,
    ) -> tuple[dict, str]:
        factory = self.graph_factory or self._load_factory()
        parameters = inspect.signature(factory).parameters
        if "data_toolkit" not in parameters or "role_llms" not in parameters:
            raise TradingAgentsConfigurationError(
                "installed TradingAgents lacks required data_toolkit/role_llms injection seams"
            )
        graph_config = self._graph_config()
        graph_config["should_cancel"] = is_cancelled

        # Identity resolution is run-scoped and deterministic; this override only
        # replaces upstream yfinance identity lookup and does not alter graph shape.
        base_factory = factory
        identity = instrument

        class DsaTradingAgentsGraph(base_factory):  # type: ignore[misc, valid-type]
            def resolve_instrument_context(self, ticker: str, asset_type: str = "stock") -> str:
                return (
                    f"The instrument is `{identity.symbol}`; name={identity.name or identity.symbol}; "
                    f"exchange={identity.exchange}; market=China A-share; currency=CNY. "
                    "Preserve this identity in every tool call and report."
                )

        role_llms = self._build_role_llms(trace_emit)
        graph = DsaTradingAgentsGraph(
            selected_analysts=("market", "social", "news", "fundamentals"),
            debug=False,
            config=graph_config,
            data_toolkit=toolkit,
            role_llms=role_llms,
        )
        try:
            state, decision = graph.propagate(instrument.symbol, trade_date, asset_type="stock")
        except RuntimeError as exc:
            if str(exc) == "TRADINGAGENTS_RUN_CANCELLED":
                raise TradingAgentsCancelledError(str(exc)) from exc
            raise
        if not isinstance(state, dict) or not str(state.get("final_trade_decision") or "").strip():
            raise RuntimeError("TradingAgents returned no final trade decision")
        return state, str(decision or state["final_trade_decision"])

    def _load_factory(self) -> type:
        try:
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except ImportError as exc:
            raise TradingAgentsConfigurationError(
                "TradingAgents is not installed; install the pinned DSA-compatible build"
            ) from exc
        try:
            installed = importlib.metadata.version("tradingagents")
        except importlib.metadata.PackageNotFoundError as exc:
            raise TradingAgentsConfigurationError("TradingAgents package metadata is unavailable") from exc
        if installed != self.config.tradingagents_version:
            raise TradingAgentsConfigurationError(
                f"TradingAgents version mismatch: expected {self.config.tradingagents_version}, got {installed}"
            )
        return TradingAgentsGraph

    def _graph_config(self) -> dict[str, Any]:
        if not self.config.model_routes:
            raise TradingAgentsConfigurationError("TradingAgents LiteLLM deployments are not configured")
        quick_route = self.config.model_routes["trader"]
        deep_route = self.config.model_routes["portfolio_manager"]
        results = self.config.results_dir.resolve()
        cache = self.config.checkpoint_db.resolve().parent
        results.mkdir(parents=True, exist_ok=True)
        cache.mkdir(parents=True, exist_ok=True)
        return {
            "project_dir": str(results),
            "results_dir": str(results),
            "data_cache_dir": str(cache),
            "memory_log_path": str(results / "decision-memory.md"),
            "memory_log_max_entries": 200,
            # Compatibility metadata for upstream helpers; graph roles use the
            # injected clients and may intentionally span providers/endpoints.
            "llm_provider": quick_route.provider,
            "quick_think_llm": quick_route.model,
            "deep_think_llm": deep_route.model,
            "backend_url": quick_route.base_url or None,
            "output_language": "Chinese",
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
            "max_recur_limit": 100,
            "checkpoint_enabled": True,
            "benchmark_ticker": "000300.SS",
            "benchmark_map": {".SS": "000300.SS", ".SZ": "399300.SZ", "": "000300.SS"},
            "temperature": None,
            "llm_max_retries": 2,
            "data_vendors": {},
            "tool_vendors": {},
        }

    def _build_role_llms(self, trace_emit: Optional[Callable[..., None]]) -> dict[str, Any]:
        if not self.config.model_routes:
            raise TradingAgentsConfigurationError("TradingAgents LiteLLM deployments are not configured")
        from tradingagents.llm_clients import create_llm_client
        from src.trader_analysis.trace import RoleTraceCallback

        clients: dict[str, Any] = {}
        for role, route in self.config.model_routes.items():
            kwargs: dict[str, Any] = {
                "timeout": self.config.provider_timeout_seconds,
                "max_retries": 2,
            }
            if route.api_key:
                kwargs["api_key"] = route.api_key
            if trace_emit is not None:
                kwargs["callbacks"] = [RoleTraceCallback(
                    role=role,
                    route=route,
                    emit=trace_emit,
                    content_limit=self.config.trace_content_max_chars,
                )]
            clients[role] = create_llm_client(
                provider=route.provider,
                model=route.model,
                base_url=route.base_url or None,
                **kwargs,
            ).get_llm()
        return clients


REPORT_FIELDS = (
    ("market_report", "market", "Market Analyst"),
    ("sentiment_report", "sentiment", "Sentiment Analyst"),
    ("news_report", "news", "News Analyst"),
    ("fundamentals_report", "fundamentals", "Fundamentals Analyst"),
    ("investment_plan", "research_decision", "Research Manager"),
    ("trader_investment_plan", "trader_plan", "Trader"),
    ("final_trade_decision", "final_decision", "Portfolio Manager"),
)
