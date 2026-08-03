"""Market evidence adapter backed by DSA data_provider."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from data_provider.base import DataFetcherManager
from src.trader_analysis.schemas.evidence import (
    EvidenceEnvelope,
    EvidenceIssue,
    EvidenceIssueSeverity,
    EvidenceStatus,
)
from src.trader_analysis.identity.resolver import (
    UnsupportedInstrumentError,
    normalize_a_share_symbol,
)


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


class MarketEvidenceAdapter:
    def __init__(self, manager: Optional[DataFetcherManager] = None) -> None:
        self.manager = manager or DataFetcherManager()

    def fetch_daily_bars(
        self,
        *,
        run_id: str,
        symbol: str,
        trade_date: date,
        min_daily_bars: int,
    ) -> EvidenceEnvelope:
        fetched_at = datetime.now()
        capability = "market_daily_bars"
        issues: List[EvidenceIssue] = []
        provider = None
        try:
            daily_kwargs = {
                "end_date": trade_date.isoformat(),
                "days": max(260, min_daily_bars),
                # Let DataFetcherManager continue through the configured
                # domestic provider chain when an early source has only a
                # shallow series.  The manager still returns the deepest
                # partial result when every source is below this preference,
                # so newly listed stocks remain eligible for degraded grading.
                "min_rows": min_daily_bars,
                # Cross-corporate-action indicators require one continuous
                # price basis.  Prefer adjusted A-share providers for this
                # analysis domain while retaining the normal fallback chain.
                "preferred_adjustments": ("qfq", "auto_adjust"),
            }
            try:
                daily_result = self.manager.get_daily_data(symbol, **daily_kwargs)
            except TypeError as exc:
                if "preferred_adjustments" not in str(exc):
                    raise
                # Preserve the documented injection seam for older custom
                # managers while still applying the continuity guard below.
                daily_kwargs.pop("preferred_adjustments")
                daily_result = self.manager.get_daily_data(symbol, **daily_kwargs)
            # DataFetcherManager returns (frame, provider).  Keep accepting a
            # bare frame as well so injected adapters and older integrations
            # remain compatible.
            if isinstance(daily_result, tuple):
                df, provider = daily_result
            else:
                df = daily_result
        except Exception as exc:
            return self._envelope(
                run_id,
                capability,
                symbol,
                trade_date,
                fetched_at,
                EvidenceStatus.UNAVAILABLE,
                None,
                None,
                None,
                [{
                    "code": "provider_error",
                    "severity": EvidenceIssueSeverity.BLOCKING,
                    "message": "日线数据源调用失败，交易员分析无法启动",
                    "details": {"error_type": type(exc).__name__},
                }],
            )

        if df is None or getattr(df, "empty", True):
            return self._envelope(
                run_id,
                capability,
                symbol,
                trade_date,
                fetched_at,
                EvidenceStatus.UNAVAILABLE,
                None,
                None,
                None,
                [{
                    "code": "provider_empty",
                    "severity": EvidenceIssueSeverity.BLOCKING,
                    "message": "未取得可用日线数据，交易员分析无法启动",
                }],
            )

        normalized = self._normalize_daily_frame(df, trade_date, provider=provider)
        rows = normalized["rows"]
        provider = normalized["provider"]
        issues.extend(normalized["issues"])
        adjustment = str(df.attrs.get("adjustment") or DataFetcherManager._daily_adjustment(provider or ""))
        if adjustment not in {"qfq", "auto_adjust", "none"}:
            adjustment = "unknown"
        price_change_result = self._normalize_price_changes(
            rows, adjustment=adjustment, provider=provider,
        )
        issues.extend(price_change_result["issues"])
        corporate_action_breaks = price_change_result["corporate_action_breaks"]
        indicator_start_date = (
            corporate_action_breaks[-1]["trade_date"]
            if corporate_action_breaks
            else (rows[0]["trade_date"] if rows else None)
        )

        if len(rows) < 3:
            issues.append(EvidenceIssue(
                code="insufficient_daily_history",
                severity=EvidenceIssueSeverity.BLOCKING,
                capability=capability,
                provider=provider,
                message=f"有效日线少于最低要求 {min_daily_bars} 个交易日",
                expected={"min_daily_bars": min_daily_bars},
                observed={"trading_days": len(rows)},
                retriable=True,
            ))
        elif len(rows) < min_daily_bars:
            issues.append(EvidenceIssue(
                code="limited_daily_history",
                severity=EvidenceIssueSeverity.WARNING,
                capability=capability,
                provider=provider,
                message=(
                    f"当前标的截至分析日仅有 {len(rows)} 个交易日历史，"
                    f"少于建议的 {min_daily_bars} 个交易日；技术指标与趋势结论必须降级解释"
                ),
                expected={"preferred_daily_bars": min_daily_bars},
                observed={"trading_days": len(rows)},
                retriable=False,
            ))

        status = EvidenceStatus.OK
        if any(issue.severity == EvidenceIssueSeverity.BLOCKING for issue in issues):
            status = EvidenceStatus.INVALID
        elif issues:
            status = EvidenceStatus.PARTIAL

        payload = {
            "adjustment": adjustment,
            "price_change_basis": "derived_from_adjacent_close",
            "corporate_action_breaks": corporate_action_breaks,
            "indicator_start_date": indicator_start_date,
            "rows": rows,
            "first_date": rows[0]["trade_date"] if rows else None,
            "last_date": rows[-1]["trade_date"] if rows else None,
            "trading_days": len(rows),
        }
        return EvidenceEnvelope(
            evidence_id=uuid.uuid4().hex,
            run_id=run_id,
            capability=capability,
            symbol=symbol,
            trade_date=trade_date,
            as_of=datetime.fromisoformat(rows[-1]["trade_date"]) if rows else None,
            fetched_at=fetched_at,
            status=status,
            provider=provider,
            source_chain=[provider] if provider else [],
            fallback_trace=[],
            is_stale=False,
            stale_seconds=None,
            missing_fields=[],
            issues=issues,
            payload=payload,
        )

    def fetch_snapshot(
        self,
        *,
        run_id: str,
        symbol: str,
        trade_date: date,
        daily_envelope: EvidenceEnvelope,
    ) -> EvidenceEnvelope:
        fetched_at = datetime.now()
        capability = "verified_market_snapshot"
        issues: List[EvidenceIssue] = []
        quote = None
        provider = None
        if trade_date == date.today():
            try:
                quote = self.manager.get_realtime_quote(symbol)
            except Exception as exc:
                issues.append(EvidenceIssue(
                    code="provider_error",
                    severity=EvidenceIssueSeverity.WARNING,
                    capability=capability,
                    provider=None,
                    message="实时行情调用失败，快照将退回到日线末行",
                    observed={"error_type": type(exc).__name__},
                    retriable=True,
                ))

        daily_rows = (daily_envelope.payload or {}).get("rows") or []
        last_bar = daily_rows[-1] if daily_rows else None
        quote_symbol = str(_value(quote, "code", _value(quote, "symbol", "")) or "")
        provider = _value(quote, "provider", _value(quote, "source", None))
        quote_price = _to_float(_value(quote, "price", _value(quote, "last_price", None)))
        price = quote_price
        quote_time = _value(
            quote,
            "provider_timestamp",
            _value(quote, "timestamp", _value(quote, "time", None)),
        )
        quote_fetched_at = _value(quote, "fetched_at", None)
        quote_as_of = self._parse_datetime(quote_time)
        quote_is_stale = _value(quote, "is_stale", None)
        quote_stale_seconds = _value(quote, "stale_seconds", None)

        if quote is not None and self._canonical_symbol(symbol) != self._canonical_symbol(quote_symbol):
            issues.append(EvidenceIssue(
                code="identity_mismatch",
                severity=EvidenceIssueSeverity.BLOCKING,
                capability=capability,
                provider=provider,
                message="实时行情返回的证券身份与请求代码不一致",
                expected={"symbol": symbol},
                observed={"quote_symbol": quote_symbol},
            ))

        if price is None and last_bar:
            price = _to_float(last_bar.get("close"))
            provider = daily_envelope.provider

        if price is None or not last_bar:
            issues.append(EvidenceIssue(
                code="verified_snapshot_unavailable",
                severity=EvidenceIssueSeverity.BLOCKING,
                capability=capability,
                provider=provider,
                message="无法确认分析使用的价格快照",
                retriable=True,
            ))

        status = EvidenceStatus.OK
        if any(issue.severity == EvidenceIssueSeverity.BLOCKING for issue in issues):
            status = EvidenceStatus.INVALID
        elif issues:
            status = EvidenceStatus.PARTIAL

        payload = {
            "last_price": price,
            "price_kind": (
                "live"
                if quote is not None and quote_price is not None
                else "close"
            ),
            "market_phase": "unknown",
            "daily_trade_date": last_bar.get("trade_date") if last_bar else None,
            "quote_time": str(quote_time) if quote_time else None,
            "quote_fetched_at": str(quote_fetched_at) if quote_fetched_at else None,
        }
        return EvidenceEnvelope(
            evidence_id=uuid.uuid4().hex,
            run_id=run_id,
            capability=capability,
            symbol=symbol,
            trade_date=trade_date,
            as_of=(quote_as_of or fetched_at) if quote is not None else datetime.combine(
                trade_date, datetime.min.time()
            ),
            fetched_at=fetched_at,
            status=status,
            provider=provider,
            source_chain=[provider] if provider else [],
            fallback_trace=[],
            is_stale=quote_is_stale if quote is not None else daily_envelope.is_stale,
            stale_seconds=(
                _to_int(quote_stale_seconds)
                if quote is not None
                else daily_envelope.stale_seconds
            ),
            missing_fields=[],
            issues=issues,
            payload=payload,
        )

    @staticmethod
    def _canonical_symbol(value: Any) -> Optional[tuple[str, str]]:
        text = str(value or "").upper().strip()
        if text.startswith(("SH.", "SZ.", "BJ.", "SS.")):
            text = text[:2] + text[3:]
        if text.startswith("SS"):
            text = "SH" + text[2:]
        if text.endswith(".SS"):
            text = text[:-3] + ".SH"
        try:
            return normalize_a_share_symbol(text)
        except UnsupportedInstrumentError:
            return None

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _normalize_daily_frame(
        self,
        df: pd.DataFrame,
        trade_date: date,
        *,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        frame = df.copy()
        columns = {str(column).lower(): column for column in frame.columns}
        date_column = columns.get("date") or columns.get("trade_date")
        provider_column = columns.get("data_source") or columns.get("source") or columns.get("provider")
        if provider_column and not frame.empty:
            provider_values = frame[provider_column].dropna()
            if not provider_values.empty:
                provider = str(provider_values.iloc[-1])

        issues: List[EvidenceIssue] = []
        required = ["open", "high", "low", "close"]
        missing = [name for name in required if name not in columns]
        if date_column is None:
            missing.append("date")
        if missing:
            issues.append(EvidenceIssue(
                code="provider_invalid_payload",
                severity=EvidenceIssueSeverity.BLOCKING,
                capability="market_daily_bars",
                provider=provider,
                message="日线数据缺少必要字段",
                missing_fields=missing,
            ))
            return {"rows": [], "provider": provider, "issues": issues}

        frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce").dt.date
        frame = frame.dropna(subset=[date_column])
        frame = frame[frame[date_column] <= trade_date]
        frame = frame.drop_duplicates(subset=[date_column], keep="last").sort_values(date_column)

        rows: List[Dict[str, Any]] = []
        for _, row in frame.iterrows():
            open_price = _to_float(row[columns["open"]])
            high = _to_float(row[columns["high"]])
            low = _to_float(row[columns["low"]])
            close = _to_float(row[columns["close"]])
            row_date = row[date_column]
            if None in (open_price, high, low, close) or min(open_price, high, low, close) <= 0:
                issues.append(EvidenceIssue(
                    code="provider_invalid_payload",
                    severity=EvidenceIssueSeverity.WARNING,
                    capability="market_daily_bars",
                    provider=provider,
                    message="日线 OHLC 存在空值或非正数",
                    observed={"trade_date": row_date.isoformat()},
                ))
                continue
            if low > min(open_price, close) or high < max(open_price, close):
                issues.append(EvidenceIssue(
                    code="provider_invalid_payload",
                    severity=EvidenceIssueSeverity.WARNING,
                    capability="market_daily_bars",
                    provider=provider,
                    message="日线 OHLC 不满足 low <= open/close <= high",
                    observed={"trade_date": row_date.isoformat()},
                ))
                continue
            volume = _to_float(row[columns["volume"]]) if "volume" in columns else 0.0
            rows.append({
                "trade_date": row_date.isoformat(),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume_shares": int(volume or 0),
                "amount_cny": _to_float(row[columns["amount"]]) if "amount" in columns else None,
                "pct_change": None,
                "provider_pct_change": self._pct_change(row, columns),
            })
        return {"rows": rows, "provider": provider, "issues": issues}

    def _normalize_price_changes(
        self,
        rows: List[Dict[str, Any]],
        *,
        adjustment: str,
        provider: Optional[str],
    ) -> Dict[str, Any]:
        """Derive returns from canonical closes and identify unadjusted breaks.

        Provider percentage fields sometimes apply a corporate-action-adjusted
        previous close even when the returned OHLC series is unadjusted.  They
        are retained for audit, but never exposed as the canonical return.
        """
        issues: List[EvidenceIssue] = []
        mismatches: List[Dict[str, Any]] = []
        corporate_action_breaks: List[Dict[str, Any]] = []
        previous_close: Optional[float] = None
        for row in rows:
            close = _to_float(row.get("close"))
            derived = (
                ((close / previous_close) - 1) * 100
                if close is not None and previous_close not in (None, 0)
                else None
            )
            row["pct_change"] = round(derived, 6) if derived is not None else None
            provider_change = _to_float(row.get("provider_pct_change"))
            if (
                derived is not None
                and provider_change is not None
                and abs(derived - provider_change) > 0.05
            ):
                mismatch = {
                    "trade_date": row.get("trade_date"),
                    "derived_pct_change": round(derived, 6),
                    "provider_pct_change": provider_change,
                }
                mismatches.append(mismatch)
                if adjustment in {"none", "unknown"} and abs(derived - provider_change) >= 5:
                    corporate_action_breaks.append(mismatch)
            previous_close = close

        if mismatches:
            issues.append(EvidenceIssue(
                code="daily_pct_change_recomputed",
                severity=EvidenceIssueSeverity.WARNING,
                capability="market_daily_bars",
                provider=provider,
                message=(
                    "数据源涨跌幅与标准化相邻收盘价不一致；canonical pct_change 已按相邻收盘价重算"
                ),
                observed={"mismatch_count": len(mismatches), "samples": mismatches[:5]},
                retriable=False,
            ))
        if corporate_action_breaks:
            issues.append(EvidenceIssue(
                code="unadjusted_corporate_action_break",
                severity=EvidenceIssueSeverity.WARNING,
                capability="market_daily_bars",
                provider=provider,
                message=(
                    "不复权日线存在疑似除权断点；跨断点技术指标已禁用，仅使用最后断点后的连续区间"
                ),
                observed={"breaks": corporate_action_breaks},
                retriable=False,
            ))
        return {
            "issues": issues,
            "corporate_action_breaks": corporate_action_breaks,
        }

    def _pct_change(self, row: pd.Series, columns: Dict[str, Any]) -> Optional[float]:
        if "pct_chg" in columns:
            return _to_float(row[columns["pct_chg"]])
        if "pct_change" in columns:
            return _to_float(row[columns["pct_change"]])
        return None

    def _envelope(
        self,
        run_id: str,
        capability: str,
        symbol: str,
        trade_date: date,
        fetched_at: datetime,
        status: EvidenceStatus,
        provider: Optional[str],
        as_of: Optional[datetime],
        payload: Optional[Dict[str, Any]],
        issue_specs: List[Dict[str, Any]],
    ) -> EvidenceEnvelope:
        issues = [
            EvidenceIssue(
                code=spec["code"],
                severity=spec["severity"],
                capability=capability,
                provider=provider,
                message=spec["message"],
                observed=spec.get("details"),
                retriable=True,
            )
            for spec in issue_specs
        ]
        return EvidenceEnvelope(
            evidence_id=uuid.uuid4().hex,
            run_id=run_id,
            capability=capability,
            symbol=symbol,
            trade_date=trade_date,
            as_of=as_of,
            fetched_at=fetched_at,
            status=status,
            provider=provider,
            source_chain=[provider] if provider else [],
            issues=issues,
            payload=payload,
        )
