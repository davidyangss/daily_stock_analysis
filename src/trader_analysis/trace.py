"""Run-scoped LangChain trace capture with recursive secret redaction."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Any, Callable

from langchain_core.callbacks import BaseCallbackHandler

from src.llm.local_cli_backend import redact_diagnostic_text

SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "cookie", "token", "password", "secret", "headers"}


def sanitize_trace(value: Any, *, limit: int) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "<redacted>" if str(key).lower().replace("-", "_") in SENSITIVE_KEYS
            else sanitize_trace(item, limit=limit)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_trace(item, limit=limit) for item in value]
    if hasattr(value, "model_dump"):
        return sanitize_trace(value.model_dump(mode="json"), limit=limit)
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = redact_diagnostic_text(str(value), limit=limit) if isinstance(value, str) else value
        return text
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    return redact_diagnostic_text(text, limit=limit)


class RoleTraceCallback(BaseCallbackHandler):
    """A minimal LangChain callback handler bound to one TradingAgents role."""

    raise_error = False
    run_inline = True

    def __init__(self, *, role: str, route: Any, emit: Callable[..., None], content_limit: int) -> None:
        self.role = role
        self.route = route
        self.emit = emit
        self.content_limit = content_limit
        self._started: dict[str, float] = {}
        self._inputs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.emit(
            event_type=event_type,
            stage=self.role,
            role=self.role,
            deployment_name=self.route.deployment_name,
            provider=self.route.provider,
            model=self.route.model,
            payload=sanitize_trace(payload, limit=self.content_limit),
        )

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs) -> None:
        operation_id = str(run_id)
        input_payload = {
            "messages": messages,
            "invocation_params": kwargs.get("invocation_params", {}),
        }
        with self._lock:
            self._started[operation_id] = time.monotonic()
            self._inputs[operation_id] = input_payload
        self._event("llm.started", {"operation_id": operation_id, "input": input_payload})

    def on_llm_end(self, response, *, run_id, **kwargs) -> None:
        operation_id = str(run_id)
        with self._lock:
            started = self._started.pop(operation_id, None)
            input_payload = self._inputs.pop(operation_id, {})
        self._event("llm.completed", {
            "operation_id": operation_id,
            "input": input_payload,
            "output": {"response": response},
            "usage": getattr(response, "llm_output", None),
            "duration_ms": round((time.monotonic() - started) * 1000) if started else None,
        })

    def on_llm_error(self, error, *, run_id, **kwargs) -> None:
        operation_id = str(run_id)
        with self._lock:
            started = self._started.pop(operation_id, None)
            input_payload = self._inputs.pop(operation_id, {})
        self._event("llm.failed", {
            "operation_id": operation_id,
            "input": input_payload,
            "error": {"type": type(error).__name__, "message": str(error)},
            "duration_ms": round((time.monotonic() - started) * 1000) if started else None,
        })
