"""DB-first K-line history loader for Agent tools.

Provides:
- ContextVar-based frozen target_date propagation across threads
- ``load_history_df``: read from DB first, DataFetcherManager fallback

Fixes #1066 – eliminates 45+ redundant HTTP requests per stock in Agent mode.
"""
from __future__ import annotations

import contextvars
import logging
from datetime import date, datetime, timedelta
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)
_CACHE_MIN_RECORDS = 30

# ---------------------------------------------------------------------------
# Frozen target date (ContextVar) – set once per stock in pipeline, read by
# all agent tool threads via copy_context().run().
# ---------------------------------------------------------------------------
_frozen_target_date: contextvars.ContextVar[Optional[date]] = contextvars.ContextVar(
    "_frozen_target_date", default=None,
)


def set_frozen_target_date(d: date) -> contextvars.Token:
    return _frozen_target_date.set(d)


def get_frozen_target_date() -> Optional[date]:
    return _frozen_target_date.get()


def reset_frozen_target_date(token: contextvars.Token) -> None:
    _frozen_target_date.reset(token)


# ---------------------------------------------------------------------------
# Internal DataFetcherManager singleton (fallback only)
# ---------------------------------------------------------------------------
_fetcher_singleton = None
_fetcher_lock = Lock()


def _get_fetcher_manager():
    global _fetcher_singleton
    if _fetcher_singleton is None:
        with _fetcher_lock:
            if _fetcher_singleton is None:
                from data_provider import DataFetcherManager
                _fetcher_singleton = DataFetcherManager()
    return _fetcher_singleton


# ---------------------------------------------------------------------------
# DB-first history loader
# ---------------------------------------------------------------------------
def _history_code_candidates(stock_code: str) -> Tuple[List[str], str]:
    from data_provider.base import canonical_stock_code, normalize_stock_code

    raw_code = str(stock_code or "").strip()
    normalized_code = canonical_stock_code(normalize_stock_code(raw_code))
    candidates: List[str] = []
    for candidate in (canonical_stock_code(raw_code), normalized_code):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates, normalized_code


def _coerce_bar_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return date.min
    if hasattr(value, "date"):
        try:
            coerced = value.date()
            return coerced if isinstance(coerced, date) else date.min
        except Exception:
            return date.min
    return date.min


def _bar_date(bar: Any) -> date:
    row_date = _coerce_bar_date(getattr(bar, "date", None))
    if row_date != date.min:
        return row_date
    if hasattr(bar, "to_dict"):
        try:
            return _coerce_bar_date((bar.to_dict() or {}).get("date"))
        except Exception:
            return date.min
    return date.min


def _select_best_bars(db, stock_code: str, start: date, end: date) -> Tuple[Optional[str], list]:
    candidates, normalized_code = _history_code_candidates(stock_code)
    best_code = None
    best_bars = []
    best_key = None

    for candidate in candidates:
        bars = list(db.get_data_range(candidate, start, end) or [])
        if not bars:
            continue
        latest_date = max(_bar_date(bar) for bar in bars)
        key = (latest_date, len(bars), candidate == normalized_code)
        if best_key is None or key > best_key:
            best_key = key
            best_code = candidate
            best_bars = bars

    return best_code, best_bars


def load_history_df(
    stock_code: str,
    days: int = 60,
    target_date: Optional[date] = None,
) -> Tuple[Optional[pd.DataFrame], str]:
    """Load K-line history, DB first with DataFetcherManager fallback.

    Returns ``(df, source)`` where *source* is ``"db_cache"`` on DB hit or the
    actual provider name on network fallback.  Returns ``(None, "none")`` when
    both paths fail.
    """
    df, source, _metadata = load_history_df_with_metadata(
        stock_code,
        days=days,
        target_date=target_date,
    )
    return df, source


def _daily_provider_attempts_since(start_index: int) -> List[Dict[str, str]]:
    """Return safe daily-data provider attempts made by this history request."""
    try:
        from src.services.run_diagnostics import current_diagnostic_snapshot

        snapshot = current_diagnostic_snapshot() or {}
        provider_runs = snapshot.get("provider_runs") or []
    except Exception:  # pragma: no cover - diagnostics must stay fail-open
        return []

    attempts: List[Dict[str, str]] = []
    for run in provider_runs[start_index:]:
        if not isinstance(run, dict) or run.get("data_type") != "daily_data":
            continue
        attempt = {
            "provider": str(run.get("provider") or "unknown"),
            "operation": str(run.get("operation") or "get_daily_data"),
        }
        if run.get("success") is False:
            attempt["reason"] = str(
                run.get("error_message_sanitized")
                or run.get("error_type")
                or "数据源未返回可用数据"
            )
        attempts.append(attempt)
    return attempts[:10]


def _daily_provider_run_count() -> int:
    try:
        from src.services.run_diagnostics import current_diagnostic_snapshot

        return len((current_diagnostic_snapshot() or {}).get("provider_runs") or [])
    except Exception:  # pragma: no cover - diagnostics must stay fail-open
        return 0


def load_history_df_with_metadata(
    stock_code: str,
    days: int = 60,
    target_date: Optional[date] = None,
) -> Tuple[Optional[pd.DataFrame], str, Dict[str, Any]]:
    """Load K-line history and return safe source/failure evidence metadata.

    The original :func:`load_history_df` remains a two-value compatibility API.
    This companion API lets report-facing tools retain the actual provider attempts
    already captured by run diagnostics without exposing raw exceptions.
    """
    from src.storage import get_db

    provider_run_start = _daily_provider_run_count()
    metadata: Dict[str, Any] = {
        "data_description": "日线K线（开盘、最高、最低、收盘、成交量）",
    }

    # Resolve effective end date
    if target_date is not None:
        end = target_date
    else:
        frozen = get_frozen_target_date()
        end = frozen if frozen else date.today()

    # Calendar-day buffer: ~1.8x trading days + margin for long holidays
    start = end - timedelta(days=int(days * 1.8) + 10)

    # --- 1. DB lookup (canonical code, then prefix-stripped fallback) ------
    try:
        db = get_db()
        _code, bars = _select_best_bars(db, stock_code, start, end)
        required_records = max(min(days, _CACHE_MIN_RECORDS), 1)
        latest_date = max((_bar_date(bar) for bar in bars), default=date.min)
        if bars and latest_date >= end and len(bars) >= required_records:
            df = pd.DataFrame([b.to_dict() for b in bars])
            logger.debug(
                "load_history_df(%s): %d bars from DB (requested %d)",
                stock_code, len(df), days,
            )
            metadata["source"] = "db_cache"
            return df, "db_cache", metadata
    except Exception as e:
        logger.debug("load_history_df(%s): DB read failed: %s", stock_code, e)

    # --- 2. Network fallback via singleton DataFetcherManager -------------
    try:
        manager = _get_fetcher_manager()
        df, source = manager.get_daily_data(stock_code, days=days)
        if df is not None and not df.empty:
            metadata["source"] = source
            metadata["provider_attempts"] = _daily_provider_attempts_since(provider_run_start)
            return df, source, metadata
    except Exception as e:
        logger.warning("load_history_df(%s): DataFetcherManager failed: %s", stock_code, e)
        try:
            from src.services.run_diagnostics import sanitize_diagnostic_text

            metadata["failure_reason"] = sanitize_diagnostic_text(e)
        except Exception:  # pragma: no cover - diagnostics must stay fail-open
            metadata["failure_reason"] = "日线数据源请求失败"

    attempts = _daily_provider_attempts_since(provider_run_start)
    if attempts:
        metadata["provider_attempts"] = attempts
        failed_attempts = [attempt for attempt in attempts if attempt.get("reason")]
        if failed_attempts:
            metadata["failure_source"] = failed_attempts[-1].get("provider")
            metadata["failure_operation"] = failed_attempts[-1].get("operation")
            metadata["failure_reason"] = failed_attempts[-1].get("reason")
    return None, "none", metadata
