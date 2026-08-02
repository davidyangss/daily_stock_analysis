from __future__ import annotations

from src.services.provider_loop import ProviderAttempt, ProviderCall, run_provider_loop


def test_provider_loop_keeps_partial_fields_and_only_fills_missing_values() -> None:
    seen_timeouts: list[float] = []

    def provider(name: str, payload: dict[str, object]) -> ProviderCall[dict[str, object]]:
        def call(timeout: float) -> dict[str, object]:
            seen_timeouts.append(timeout)
            return payload

        return ProviderCall(name, call)

    def merge(current: dict[str, object], candidate: dict[str, object], _provider: str) -> dict[str, object]:
        merged = dict(current)
        for key, value in candidate.items():
            if merged.get(key) is None and value is not None:
                merged[key] = value
        return merged

    result = run_provider_loop(
        [
            provider("first", {"revenue_yoy": None, "roe": 6.6}),
            provider("second", {"revenue_yoy": 17.7, "roe": 999}),
        ],
        initial={"revenue_yoy": None, "roe": None},
        merge=merge,
        is_usable=lambda value: any(item is not None for item in value.values()),
        is_complete=lambda value: all(item is not None for item in value.values()),
        total_timeout_seconds=60,
        provider_timeout_seconds=15,
    )

    assert result.value == {"revenue_yoy": 17.7, "roe": 6.6}
    assert result.complete is True
    assert [attempt.provider for attempt in result.attempts] == ["first", "second"]
    assert all(0 < timeout <= 15 for timeout in seen_timeouts)


def test_provider_loop_continues_after_failure_without_losing_previous_data() -> None:
    def failed(_timeout: float) -> dict[str, object]:
        raise TimeoutError("slow fallback")

    result = run_provider_loop(
        [
            ProviderCall("first", lambda _timeout: {"roe": 6.6}),
            ProviderCall("second", failed),
        ],
        initial={},
        merge=lambda current, candidate, _provider: {**current, **candidate},
        is_usable=bool,
        is_complete=lambda value: "roe" in value and "revenue_yoy" in value,
        total_timeout_seconds=60,
        provider_timeout_seconds=15,
    )

    assert result.value == {"roe": 6.6}
    assert [attempt.status for attempt in result.attempts] == ["ok", "timeout"]
    assert result.attempts[-1].error == "TimeoutError"


def test_provider_loop_records_configured_but_unavailable_provider_as_skipped() -> None:
    result = run_provider_loop(
        [
            ProviderCall("disabled", skip_reason="disabled"),
            ProviderCall("unsupported", skip_reason="not_supported"),
            ProviderCall("working", lambda _timeout: {"value": 1}),
        ],
        initial={},
        merge=lambda current, candidate, _provider: {**current, **candidate},
        is_usable=bool,
        is_complete=lambda value: "value" in value,
        total_timeout_seconds=60,
        provider_timeout_seconds=15,
    )

    assert result.value == {"value": 1}
    assert [(item.provider, item.status, item.error) for item in result.attempts] == [
        ("disabled", "skipped", "disabled"),
        ("unsupported", "skipped", "not_supported"),
        ("working", "ok", None),
    ]


def test_provider_loop_emits_live_start_and_terminal_attempt_events() -> None:
    events: list[tuple[str, str]] = []

    result = run_provider_loop(
        [
            ProviderCall("disabled", skip_reason="disabled"),
            ProviderCall("empty", lambda _timeout: {}),
            ProviderCall("working", lambda _timeout: {"value": 1}),
        ],
        initial={},
        merge=lambda current, candidate, _provider: {**current, **candidate},
        is_usable=bool,
        is_complete=lambda value: "value" in value,
        total_timeout_seconds=60,
        provider_timeout_seconds=15,
        on_start=lambda provider, _timeout: events.append((provider, "started")),
        on_attempt=lambda attempt: events.append((attempt.provider, attempt.status)),
    )

    assert result.complete is True
    assert events == [
        ("disabled", "skipped"),
        ("empty", "started"),
        ("empty", "empty"),
        ("working", "started"),
        ("working", "ok"),
    ]


def test_provider_loop_immediately_falls_back_after_returned_failure_payload() -> None:
    calls: list[str] = []

    def usable(candidate: dict[str, object]) -> bool:
        return candidate.get("status") not in {"failed", "not_supported"} and bool(candidate.get("growth"))

    result = run_provider_loop(
        [
            ProviderCall("failed", lambda _timeout: calls.append("failed") or {"status": "failed", "growth": {}}),
            ProviderCall("working", lambda _timeout: calls.append("working") or {"status": "partial", "growth": {"roe": 6.6}}),
        ],
        initial={},
        merge=lambda current, candidate, _provider: {**current, **candidate},
        is_usable=usable,
        is_complete=lambda value: bool(value.get("growth")),
        total_timeout_seconds=60,
        provider_timeout_seconds=15,
        classify_unusable=lambda candidate: (
            "failed",
            "provider returned failed",
        ) if candidate.get("status") == "failed" else ("empty", None),
    )

    assert calls == ["failed", "working"]
    assert [attempt.status for attempt in result.attempts] == ["failed", "ok"]
    assert result.attempts[0].error == "provider returned failed"
    assert result.complete is True


def test_provider_loop_diagnostic_callback_failures_do_not_break_fallback() -> None:
    def broken_callback(*_args: object) -> None:
        raise RuntimeError("diagnostic storage unavailable")

    result = run_provider_loop(
        [ProviderCall("working", lambda _timeout: {"value": 1})],
        initial={},
        merge=lambda current, candidate, _provider: {**current, **candidate},
        is_usable=bool,
        is_complete=lambda value: "value" in value,
        total_timeout_seconds=60,
        provider_timeout_seconds=15,
        on_start=broken_callback,
        on_attempt=broken_callback,
    )

    assert result.value == {"value": 1}
    assert result.complete is True


def test_provider_loop_classifies_timeout_separately_from_immediate_failure() -> None:
    result = run_provider_loop(
        [
            ProviderCall("timeout", lambda _timeout: (_ for _ in ()).throw(TimeoutError("no response"))),
            ProviderCall("failed", lambda _timeout: (_ for _ in ()).throw(RuntimeError("bad response"))),
        ],
        initial={},
        merge=lambda current, candidate, _provider: {**current, **candidate},
        is_usable=bool,
        is_complete=lambda _value: False,
        total_timeout_seconds=60,
        provider_timeout_seconds=15,
    )

    assert [attempt.status for attempt in result.attempts] == ["timeout", "failed"]
