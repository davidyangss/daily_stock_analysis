"""Strict integration boundary for the patched upstream TradingAgents graph."""

from __future__ import annotations

import importlib.metadata
import inspect
from typing import Any, Callable, Optional
from urllib.parse import urlparse

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
        run_id: str,
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

        # Identity resolution is run-scoped and deterministic; this override only
        # replaces upstream yfinance identity lookup and does not alter graph shape.
        base_factory = factory
        identity = instrument

        class DsaTradingAgentsGraph(base_factory):  # type: ignore[misc, valid-type]
            def resolve_instrument_context(self, ticker: str, asset_type: str = "stock") -> str:
                return (
                    f"The instrument is `{identity.symbol}`; name={identity.name or identity.symbol}; "
                    f"exchange={identity.exchange}; market=China A-share; currency=CNY. "
                    "Preserve this identity in every tool call and report. "
                    "所有报告正文、标题、评级和结论必须使用简体中文；第一句话也必须使用中文，不得用英文段落或英文标题。"
                    "市场技术分析不得以 `FINAL TRANSACTION PROPOSAL` 等英文固定短语开头；"
                    "如确需标记最终交易建议，请写成 `最终交易建议：买入/持有/卖出`。"
                )

            def _run_signature(self, asset_type: str) -> str:
                # An API run is an immutable execution attempt. Never resume a
                # partially written LangGraph message sequence from another
                # run for the same symbol/date.
                return f"{super()._run_signature(asset_type)}|dsa_run={run_id}"

        self._usage_stock_code = instrument.symbol
        role_llms = self._build_role_llms(trace_emit)
        graph = DsaTradingAgentsGraph(
            selected_analysts=("market", "social", "news", "fundamentals"),
            debug=False,
            config=graph_config,
            data_toolkit=toolkit,
            role_llms=role_llms,
        )
        # Upstream deep-copies graph_config during construction. A bound
        # threading.Event method contains an unpicklable lock, so attach the
        # run-scoped cancellation callback only after that copy boundary.
        graph.config["should_cancel"] = is_cancelled
        # TradingAgents 0.3.1 only retains streamed state chunks inside its
        # debug branch. Cancellation also selects streaming, so leaving debug
        # false discards every chunk and produces an empty final state. Enable
        # the upstream branch until the pinned dependency includes that
        # one-line trace-append indentation fix.
        graph.debug = True
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
            "output_language": "Simplified Chinese",
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
        usage_stock_code = getattr(self, "_usage_stock_code", None)
        for role, route in self.config.model_routes.items():
            client_provider = _tradingagents_provider(route.provider, route.base_url)
            kwargs: dict[str, Any] = {
                "timeout": self.config.provider_timeout_seconds,
                "max_retries": 2,
            }
            if route.api_key:
                kwargs["api_key"] = route.api_key
            kwargs["callbacks"] = [RoleTraceCallback(
                role=role,
                route=route,
                emit=trace_emit or (lambda **_values: None),
                content_limit=self.config.trace_content_max_chars,
                stock_code=usage_stock_code,
            )]
            clients[role] = create_llm_client(
                provider=client_provider,
                model=route.model,
                base_url=route.base_url or None,
                **kwargs,
            ).get_llm()
        return clients


def _tradingagents_provider(provider: str, base_url: str) -> str:
    """Use the generic client for non-native OpenAI-compatible gateways."""
    if provider.lower() != "openai" or not base_url:
        return provider
    parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}")
    host = (parsed.hostname or "").lower()
    if host == "api.openai.com" or host.endswith(".openai.com"):
        return provider
    return "openai_compatible"
