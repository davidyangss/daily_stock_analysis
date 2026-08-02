"""Shared sequential provider-loop primitives.

The loop owns ordering, budgets and attempt metadata.  Capability owners still
own validation and merge semantics: a daily-bar series is atomic, while a
fundamental bundle may safely fill missing fields when period metadata agrees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Callable, Generic, Iterable, Mapping, Optional, TypeVar


T = TypeVar("T")
R = TypeVar("R")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderCall(Generic[T]):
    name: str
    call: Optional[Callable[[float], T]] = None
    skip_reason: Optional[str] = None


@dataclass
class ProviderAttempt:
    provider: str
    status: str
    duration_ms: int
    error: Optional[str] = None


@dataclass
class ProviderLoopResult(Generic[R]):
    value: R
    attempts: list[ProviderAttempt] = field(default_factory=list)
    complete: bool = False
    budget_exhausted: bool = False


def run_provider_loop(
    providers: Iterable[ProviderCall[T]],
    *,
    initial: R,
    merge: Callable[[R, T, str], R],
    is_usable: Callable[[T], bool],
    is_complete: Callable[[R], bool],
    total_timeout_seconds: float,
    provider_timeout_seconds: float,
    provider_timeout_overrides: Optional[Mapping[str, float]] = None,
    error_summary: Callable[[BaseException], str] = lambda exc: type(exc).__name__,
    on_start: Optional[Callable[[str, float], None]] = None,
    on_attempt: Optional[Callable[[ProviderAttempt], None]] = None,
    classify_unusable: Optional[Callable[[T], tuple[str, Optional[str]]]] = None,
) -> ProviderLoopResult[R]:
    """Run ordered providers and retain every usable partial result.

    ``call`` receives the smaller of the per-provider limit and remaining total
    budget.  It must enforce that timeout at its actual I/O boundary; this loop
    intentionally does not create unkillable timeout threads.
    """

    total_timeout = max(0.0, float(total_timeout_seconds))
    provider_timeout = max(0.0, float(provider_timeout_seconds))
    timeout_overrides = {
        str(name).strip().lower(): max(0.0, float(value))
        for name, value in (provider_timeout_overrides or {}).items()
    }
    deadline = time.monotonic() + total_timeout
    result = ProviderLoopResult(value=initial)

    for provider in providers:
        if is_complete(result.value):
            result.complete = True
            break
        if provider.skip_reason or provider.call is None:
            attempt = ProviderAttempt(
                provider.name,
                "skipped",
                0,
                provider.skip_reason or "not_available",
            )
            result.attempts.append(attempt)
            if on_attempt is not None:
                try:
                    on_attempt(attempt)
                except Exception as exc:  # diagnostics must never break fallback
                    logger.warning("provider attempt callback failed: %s", exc)
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result.budget_exhausted = True
            break
        timeout = min(
            timeout_overrides.get(provider.name.strip().lower(), provider_timeout),
            remaining,
        )
        if timeout <= 0:
            result.budget_exhausted = True
            break

        started = time.monotonic()
        if on_start is not None:
            try:
                on_start(provider.name, timeout)
            except Exception as exc:  # diagnostics must never break fallback
                logger.warning("provider start callback failed: %s", exc)
        try:
            candidate = provider.call(timeout)
            duration_ms = int((time.monotonic() - started) * 1000)
            if is_usable(candidate):
                result.value = merge(result.value, candidate, provider.name)
                attempt = ProviderAttempt(provider.name, "ok", duration_ms)
            else:
                status, error = (
                    classify_unusable(candidate)
                    if classify_unusable is not None
                    else ("empty", None)
                )
                attempt = ProviderAttempt(provider.name, status, duration_ms, error)
        except Exception as exc:
            attempt = ProviderAttempt(
                provider.name,
                "timeout" if isinstance(exc, TimeoutError) else "failed",
                int((time.monotonic() - started) * 1000),
                error_summary(exc),
            )
        result.attempts.append(attempt)
        if on_attempt is not None:
            try:
                on_attempt(attempt)
            except Exception as exc:  # diagnostics must never break fallback
                logger.warning("provider attempt callback failed: %s", exc)

    result.complete = is_complete(result.value)
    if not result.complete and time.monotonic() >= deadline:
        result.budget_exhausted = True
    return result
