"""Minimal cross-model fallback wrapper for TradingAgents role LLMs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain_core.runnables import Runnable


_FALLBACK_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_FALLBACK_ERROR_NAMES = (
    "apiconnectionerror",
    "apitimeouterror",
    "connectionerror",
    "internalservererror",
    "ratelimiterror",
    "remotedisconnected",
    "serviceunavailable",
    "timeout",
)
_NON_FALLBACK_ERROR_NAMES = (
    "authenticationerror",
    "contentpolicyviolationerror",
    "permissiondeniederror",
)
_RECOVERABLE_BAD_REQUEST_MARKERS = (
    "context_length_exceeded",
    "service_unavailable",
    "upstream stream ended without a terminal response event",
)


def _error_signals(exc: BaseException) -> tuple[set[int], str]:
    """Collect status codes and safe classification text from nested errors."""
    statuses: set[int] = set()
    text_parts: list[str] = []
    pending: list[Any] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, BaseException):
            text_parts.extend((type(current).__name__, str(current)))
            pending.extend((
                getattr(current, "body", None),
                getattr(current, "response", None),
                getattr(current, "__cause__", None),
                getattr(current, "__context__", None),
            ))
            for attr in ("status_code", "code"):
                value = getattr(current, attr, None)
                if isinstance(value, int):
                    statuses.add(value)
            continue
        if isinstance(current, Mapping):
            for key, value in current.items():
                if str(key).lower() in {"status", "status_code"} and isinstance(value, int):
                    statuses.add(value)
                elif str(key).lower() in {"code", "error", "message", "type"}:
                    text_parts.append(str(value))
                if isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes)):
                    pending.append(value)
            continue
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            pending.extend(current)
            continue
        status = getattr(current, "status_code", None)
        if isinstance(status, int):
            statuses.add(status)
        text_parts.append(str(current))
    return statuses, " ".join(text_parts).lower()


def is_trader_fallback_error(exc: BaseException) -> bool:
    """Return whether another configured model may recover this failure."""
    statuses, text = _error_signals(exc)
    if any(name in text for name in _NON_FALLBACK_ERROR_NAMES):
        return False
    if any(marker in text for marker in _RECOVERABLE_BAD_REQUEST_MARKERS):
        return True
    if statuses & _FALLBACK_STATUS_CODES:
        return True
    if "badrequesterror" in text or isinstance(exc, (TypeError, ValueError)):
        return False
    return any(name in text for name in _FALLBACK_ERROR_NAMES)


class TraderFallbackLLM(Runnable[Any, Any]):
    """Preserve TradingAgents chat-model APIs while trying fallback models."""

    def __init__(
        self,
        primary: Runnable[Any, Any],
        fallbacks: Sequence[Runnable[Any, Any]],
        *,
        on_fallback: Callable[[int, int, BaseException], None] | None = None,
    ) -> None:
        self.primary = primary
        self.fallbacks = tuple(fallbacks)
        self.on_fallback = on_fallback

    @property
    def _candidates(self) -> tuple[Runnable[Any, Any], ...]:
        return (self.primary, *self.fallbacks)

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        last_index = len(self._candidates) - 1
        for index, candidate in enumerate(self._candidates):
            try:
                return candidate.invoke(input, config=config, **kwargs)
            except Exception as exc:
                if index >= last_index or not is_trader_fallback_error(exc):
                    raise
                if self.on_fallback is not None:
                    self.on_fallback(index, index + 1, exc)
        raise RuntimeError("unreachable trader LLM fallback state")

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        last_index = len(self._candidates) - 1
        for index, candidate in enumerate(self._candidates):
            try:
                return await candidate.ainvoke(input, config=config, **kwargs)
            except Exception as exc:
                if index >= last_index or not is_trader_fallback_error(exc):
                    raise
                if self.on_fallback is not None:
                    self.on_fallback(index, index + 1, exc)
        raise RuntimeError("unreachable trader LLM fallback state")

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "TraderFallbackLLM":
        return self._bind("bind_tools", tools, **kwargs)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "TraderFallbackLLM":
        return self._bind("with_structured_output", schema, **kwargs)

    def _bind(self, method: str, *args: Any, **kwargs: Any) -> "TraderFallbackLLM":
        bound = [getattr(candidate, method)(*args, **kwargs) for candidate in self._candidates]
        return TraderFallbackLLM(bound[0], bound[1:], on_fallback=self.on_fallback)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.primary, name)
