"""Resolve per-role TradingAgents LLMs from DSA LiteLLM deployments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


ROLE_DEFAULTS = {
    "market": "quick",
    "sentiment": "quick",
    "news": "quick",
    "fundamentals": "quick",
    "research_debate": "quick",
    "research_manager": "deep",
    "trader": "quick",
    "risk_debate": "quick",
    "portfolio_manager": "deep",
}


class ModelRouteConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ModelRoute:
    deployment_name: str
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""

    def public_dict(self) -> dict[str, str]:
        return {
            "deployment_name": self.deployment_name,
            "provider": self.provider,
            "model": self.model,
        }


def _split_model(raw: str) -> tuple[str, str]:
    if "/" not in raw:
        return "", raw
    provider, model = raw.split("/", 1)
    return {"gemini": "google"}.get(provider.lower(), provider.lower()), model


def resolve_model_routes(
    model_list: list[dict[str, Any]],
    *,
    quick_name: str,
    deep_name: str,
    role_names: Mapping[str, str],
    legacy_provider: str = "",
    legacy_base_url: str = "",
) -> dict[str, ModelRoute]:
    deployments = {
        str(item.get("model_name") or "").strip(): item
        for item in model_list
        if isinstance(item, dict) and str(item.get("model_name") or "").strip()
    }

    def resolve(name: str) -> ModelRoute:
        name = name.strip()
        if not name:
            raise ModelRouteConfigurationError("empty LiteLLM deployment name")
        item = deployments.get(name)
        if item is None:
            # Backward compatibility for the old provider/model configuration.
            provider, model = _split_model(name)
            if not provider:
                provider = legacy_provider.strip().lower()
            if not provider:
                raise ModelRouteConfigurationError(
                    f"LiteLLM deployment '{name}' does not exist in llm_model_list"
                )
            return ModelRoute(name, provider, model, legacy_base_url)
        params = item.get("litellm_params") or {}
        # Older DSA-generated route lists may use model_name itself as the
        # provider/model wire identifier and only store endpoint metadata.
        wire = str(params.get("model") or name).strip()
        provider, model = _split_model(wire)
        provider = str(params.get("custom_llm_provider") or provider).strip().lower()
        if not provider or not model:
            raise ModelRouteConfigurationError(
                f"LiteLLM deployment '{name}' must define litellm_params.model as provider/model"
            )
        return ModelRoute(
            deployment_name=name,
            provider=provider,
            model=model,
            base_url=str(params.get("api_base") or "").strip(),
            api_key=str(params.get("api_key") or "").strip(),
        )

    defaults = {"quick": resolve(quick_name), "deep": resolve(deep_name)}
    return {
        role: resolve(str(role_names.get(role) or ""))
        if str(role_names.get(role) or "").strip()
        else defaults[tier]
        for role, tier in ROLE_DEFAULTS.items()
    }
