"""Shared sequential provider-loop primitives.

The loop owns ordering, budgets and attempt metadata.  Capability owners still
own validation and merge semantics: a daily-bar series is atomic, while a
fundamental bundle may safely fill missing fields when period metadata agrees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import random
import time
from typing import Callable, Generic, Iterable, Mapping, Optional, TypeVar


T = TypeVar("T")
R = TypeVar("R")

logger = logging.getLogger(__name__)


def is_retryable_provider_error(exc: BaseException) -> bool:
    """Return whether a provider failure is likely transient.

    Configuration, authentication, validation and unsupported-capability errors
    deliberately remain non-retryable and fall through to the next provider.
    """
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (TimeoutError, ConnectionError)):
            return True
        status = getattr(getattr(current, "response", None), "status_code", None)
        status = status if status is not None else getattr(current, "status_code", None)
        if status in {408, 425, 429, 500, 502, 503, 504}:
            return True
        name = type(current).__name__.lower()
        text = str(current).lower()
        if any(token in name for token in ("timeout", "connectionerror", "ratelimit", "remotedisconnected", "incompleteread")):
            return True
        if any(token in text for token in ("connection reset", "connection aborted", "temporarily unavailable", "too many requests")):
            return True
        for linked in (getattr(current, "__cause__", None), getattr(current, "__context__", None)):
            if isinstance(linked, BaseException):
                pending.append(linked)
    return False


def call_provider_with_retry(
    call: Callable[[], T],
    *,
    provider: str,
    max_attempts: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
    deadline: Optional[float] = None,
) -> T:
    """Retry one already-eligible provider only for transient exceptions."""
    attempts = max(1, int(max_attempts))
    base_delay = max(0.0, float(base_delay_seconds))
    max_delay = max(base_delay, float(max_delay_seconds))
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if attempt >= attempts or not is_retryable_provider_error(exc):
                raise
            delay_cap = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = random.uniform(0.0, delay_cap) if delay_cap > 0 else 0.0
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or delay >= remaining:
                    raise
            logger.warning(
                "数据源 %s 瞬时失败，%.2f 秒后重试（%d/%d）: %s",
                provider,
                delay,
                attempt + 1,
                attempts,
                type(exc).__name__,
            )
            if delay > 0:
                time.sleep(delay)
    raise RuntimeError("unreachable provider retry state")


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
    max_attempts: int = 1,
    retry_base_delay_seconds: float = 0.5,
    retry_max_delay_seconds: float = 2.0,
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
            candidate = call_provider_with_retry(
                lambda: provider.call(min(timeout, max(0.0, deadline - time.monotonic()))),
                provider=provider.name,
                max_attempts=max_attempts,
                base_delay_seconds=retry_base_delay_seconds,
                max_delay_seconds=retry_max_delay_seconds,
                deadline=deadline,
            )
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
