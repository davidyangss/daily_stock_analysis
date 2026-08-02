"""Bounded public-page reader for trader-analysis evidence enrichment."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class BrowserReaderFailure(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class BrowserReaderConfig:
    enabled: bool = False
    command: str = "agent-browser"
    max_pages: int = 3
    timeout_seconds: int = 20
    max_chars: int = 12000
    allowed_domains: tuple[str, ...] = ("xueqiu.com",)


class CommunityPageReader:
    """Read public pages through agent-browser without exposing browser tools to the LLM."""

    def __init__(self, config: BrowserReaderConfig) -> None:
        self.config = config

    def enrich_items(self, items: Iterable[dict[str, Any]], *, run_id: str) -> list[dict[str, Any]]:
        rows = [dict(item) for item in items]
        if not self.config.enabled:
            return rows
        for item in rows[: self.config.max_pages]:
            item.update(self.read(str(item.get("url") or ""), run_id=run_id))
        return rows

    def read(self, url: str, *, run_id: str) -> dict[str, Any]:
        fetched_at = datetime.now().isoformat()
        try:
            domain = self._validate_url(url)
            executable = shutil.which(self.config.command)
            if executable is None:
                raise BrowserReaderFailure("command_unavailable")
            session = f"dsa-trader-{run_id[:12]}-{uuid.uuid4().hex[:8]}"
            base_command = [
                executable,
                "--session", session,
                "--allowed-domains", ",".join(self.config.allowed_domains),
                "--content-boundaries",
                "--max-output", str(self.config.max_chars),
                "--json",
            ]
            deadline = time.monotonic() + self.config.timeout_seconds
            browser_env = {
                key: value
                for key in ("PATH", "HOME", "XDG_RUNTIME_DIR", "TMPDIR", "LANG", "SSL_CERT_FILE")
                if (value := os.environ.get(key))
            }
            # Never inherit provider credentials, browser auth state, plugins,
            # auto-connect, or restore behavior into evidence collection.
            browser_env.update({
                "AGENT_BROWSER_PLUGINS": "[]",
                "AGENT_BROWSER_AUTO_CONNECT": "false",
                "AGENT_BROWSER_RESTORE": "",
            })
            try:
                opened = self._run(base_command + ["open", url], deadline=deadline, env=browser_env)
                if opened.returncode != 0:
                    raise BrowserReaderFailure("open_failed")
                completed = self._run(base_command + ["read"], deadline=deadline, env=browser_env)
                if completed.returncode != 0:
                    raise BrowserReaderFailure("read_failed")
                raw_content = self._extract_content(completed.stdout)
            finally:
                try:
                    subprocess.run(
                        base_command + ["close"], capture_output=True, text=True,
                        timeout=3, check=False, env=browser_env,
                    )
                except Exception:
                    pass
            if not self._is_meaningful_content(raw_content):
                raise BrowserReaderFailure("low_quality_content")
            truncated = len(raw_content) > self.config.max_chars
            content = raw_content[: self.config.max_chars]
            return {
                "content_excerpt": content,
                "content_kind": "browser_excerpt",
                "content_reader": "agent-browser",
                "content_source_domain": domain,
                "content_fetched_at": fetched_at,
                "content_truncated": truncated,
                "content_fetch_status": "ok",
            }
        except subprocess.TimeoutExpired:
            return self._failure("timeout", fetched_at)
        except BrowserReaderFailure as exc:
            return self._failure(exc.reason, fetched_at)
        except Exception as exc:
            logger.info("Trader browser evidence read skipped for %s: %s", url, type(exc).__name__)
            return self._failure(type(exc).__name__, fetched_at)

    def _validate_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("browser evidence URL must be a public HTTPS URL")
        host = parsed.hostname.rstrip(".").lower()
        if not any(host == domain or host.endswith(f".{domain}") for domain in self.config.allowed_domains):
            raise ValueError("browser evidence URL domain is not allowlisted")
        addresses = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        if not addresses:
            raise ValueError("browser evidence URL did not resolve")
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise ValueError("browser evidence URL resolved to a non-public address")
        return host

    @staticmethod
    def _extract_content(raw: str) -> str:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip()

        def find(value: Any) -> str:
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, dict):
                for key in ("content", "text", "markdown", "result", "data"):
                    if key in value and (result := find(value[key])):
                        return result
            return ""

        return find(payload)

    @staticmethod
    def _is_meaningful_content(content: str) -> bool:
        normalized = content.strip().lower()
        if len(normalized) < 120:
            return False
        return not any(marker in normalized for marker in (
            "_waf_", "cf_app_waf", "access denied", "captcha", "verify you are human",
            "访问验证", "请进行验证", "请完成验证", "请按住滑块",
        ))

    @staticmethod
    def _run(command: list[str], *, deadline: float, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, 0)
        return subprocess.run(
            command, capture_output=True, text=True, timeout=remaining,
            check=False, env=env,
        )

    @staticmethod
    def _failure(reason: str, fetched_at: str) -> dict[str, Any]:
        return {
            "content_kind": "search_snippet",
            "content_reader": "agent-browser",
            "content_fetched_at": fetched_at,
            "content_fetch_status": "unavailable",
            "content_fetch_reason": reason,
        }
