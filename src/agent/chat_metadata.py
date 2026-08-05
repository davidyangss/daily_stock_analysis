"""Persist display-only Agent Chat metadata inside the visible message record."""

from __future__ import annotations

import base64


def append_chat_model_marker(content: str, model: str) -> str:
    """Append an invisible, renderer-readable marker for actual runtime models."""
    normalized = ", ".join(dict.fromkeys(part.strip() for part in str(model or "").split(",") if part.strip()))
    if not normalized:
        return content
    encoded = base64.b64encode(normalized.encode("utf-8")).decode("ascii")
    return f"{content.rstrip()}\n\n<!-- dsa-chat-model:{encoded} -->"
