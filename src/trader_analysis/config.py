"""Configuration for the independent trader-analysis domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.trader_analysis.model_routes import ModelRoute, ROLE_DEFAULTS, resolve_model_routes


def _model_provider(model: str) -> str:
    prefix = model.split("/", 1)[0].lower() if "/" in model else ""
    return {"gemini": "google"}.get(prefix, prefix)


def _wire_model(model: str) -> str:
    return model.split("/", 1)[1] if "/" in model else model


def _model_base_url(config: Any, model: str) -> str:
    for deployment in getattr(config, "llm_model_list", []) or []:
        if not isinstance(deployment, dict):
            continue
        params = deployment.get("litellm_params") or {}
        if str(deployment.get("model_name") or "") == model:
            return str(params.get("api_base") or "")
    return str(getattr(config, "openai_base_url", "") or "")


@dataclass(frozen=True)
class TraderAnalysisConfig:
    enabled: bool
    max_concurrency: int
    queue_limit: int
    task_timeout_seconds: int
    provider_timeout_seconds: int
    results_dir: Path
    checkpoint_db: Path
    min_daily_bars: int
    stale_threshold_seconds: int
    tradingagents_version: str
    tradingagents_commit: str
    llm_provider: str
    quick_model: str
    deep_model: str
    llm_backend_url: str
    model_routes: dict[str, ModelRoute] = field(default_factory=dict)
    trace_content_max_chars: int = 65536
    browser_reader_enabled: bool = False
    browser_reader_command: str = "agent-browser"
    browser_reader_max_pages: int = 3
    browser_reader_timeout_seconds: int = 20
    browser_reader_max_chars: int = 12000
    browser_reader_allowed_domains: tuple[str, ...] = (
        "xueqiu.com", "zhihu.com", "weibo.com", "sse.com.cn", "szse.cn",
        "cninfo.com.cn", "cnstock.com", "eastmoney.com", "sina.com.cn",
    )
    data_toolkit_version: str = "dsa-trader-toolkit-v2"
    evidence_policy_version: str = "trader-evidence-policy-v2"

    @classmethod
    def from_app_config(cls, config: Any) -> "TraderAnalysisConfig":
        quick_raw = str(
            getattr(config, "trader_analysis_quick_model", "")
            or getattr(config, "agent_litellm_model", "")
            or getattr(config, "litellm_model", "")
        )
        deep_raw = str(
            getattr(config, "trader_analysis_deep_model", "")
            or getattr(config, "litellm_model", "")
        )
        provider = str(getattr(config, "trader_analysis_llm_provider", "") or "")
        quick_provider = _model_provider(quick_raw)
        deep_provider = _model_provider(deep_raw)
        if not provider and quick_provider and deep_provider and quick_provider != deep_provider:
            provider = ""
        else:
            provider = provider or quick_provider or deep_provider
        role_names = {
            role: str(getattr(config, f"trader_analysis_model_{role}", "") or "")
            for role in ROLE_DEFAULTS
        }
        routes = resolve_model_routes(
            list(getattr(config, "llm_model_list", []) or []),
            quick_name=quick_raw,
            deep_name=deep_raw,
            role_names=role_names,
            legacy_provider=provider,
            legacy_base_url=str(getattr(config, "trader_analysis_llm_backend_url", "") or ""),
        ) if quick_raw and deep_raw else {}
        return cls(
            enabled=bool(getattr(config, "trader_analysis_enabled", False)),
            max_concurrency=int(getattr(config, "trader_analysis_max_concurrency", 1)),
            queue_limit=int(getattr(config, "trader_analysis_queue_limit", 8)),
            task_timeout_seconds=int(getattr(config, "trader_analysis_task_timeout_seconds", 900)),
            provider_timeout_seconds=int(getattr(config, "trader_analysis_provider_timeout_seconds", 120)),
            results_dir=Path(str(getattr(config, "trader_analysis_results_dir", "data/trader_analysis"))),
            checkpoint_db=Path(str(getattr(
                config,
                "trader_analysis_checkpoint_db",
                "data/trader_analysis/checkpoints.sqlite",
            ))),
            min_daily_bars=int(getattr(config, "trader_analysis_min_daily_bars", 30)),
            stale_threshold_seconds=int(getattr(config, "trader_analysis_stale_threshold_seconds", 86400)),
            tradingagents_version=str(getattr(config, "trader_analysis_tradingagents_version", "0.3.1")),
            tradingagents_commit=str(getattr(config, "trader_analysis_tradingagents_commit", "")),
            llm_provider=provider,
            quick_model=_wire_model(quick_raw),
            deep_model=_wire_model(deep_raw),
            llm_backend_url=str(
                getattr(config, "trader_analysis_llm_backend_url", "")
                or _model_base_url(config, quick_raw)
            ),
            model_routes=routes,
            trace_content_max_chars=int(getattr(config, "trader_analysis_trace_content_max_chars", 65536)),
            browser_reader_enabled=bool(getattr(config, "trader_analysis_browser_reader_enabled", False)),
            browser_reader_command=str(getattr(
                config, "trader_analysis_browser_reader_command", "agent-browser",
            )),
            browser_reader_max_pages=int(getattr(config, "trader_analysis_browser_reader_max_pages", 3)),
            browser_reader_timeout_seconds=int(getattr(
                config, "trader_analysis_browser_reader_timeout_seconds", 20,
            )),
            browser_reader_max_chars=int(getattr(config, "trader_analysis_browser_reader_max_chars", 12000)),
            browser_reader_allowed_domains=tuple(getattr(
                config, "trader_analysis_browser_reader_allowed_domains", ["xueqiu.com"],
            )),
        )
