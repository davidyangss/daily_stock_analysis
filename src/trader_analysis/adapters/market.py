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
            df = self.manager.get_daily_data(symbol, end_date=trade_date.isoformat(), days=max(260, min_daily_bars))
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

        normalized = self._normalize_daily_frame(df, trade_date)
        rows = normalized["rows"]
        provider = normalized["provider"]
        issues.extend(normalized["issues"])

        if len(rows) < min_daily_bars:
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

        status = EvidenceStatus.OK
        if any(issue.severity == EvidenceIssueSeverity.BLOCKING for issue in issues):
            status = EvidenceStatus.INVALID
        elif issues:
            status = EvidenceStatus.PARTIAL

        payload = {
            "adjustment": "unknown",
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
        quote_symbol = str(_value(quote, "code", _value(quote, "symbol", symbol)) or symbol)
        provider = _value(quote, "provider", _value(quote, "source", None))
        price = _to_float(_value(quote, "price", _value(quote, "last_price", None)))
        quote_time = _value(quote, "timestamp", _value(quote, "time", None))

        if quote is not None and symbol not in quote_symbol:
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
                if quote is not None and _to_float(_value(quote, "price", None)) is not None
                else "close"
            ),
            "market_phase": "unknown",
            "daily_trade_date": last_bar.get("trade_date") if last_bar else None,
            "quote_time": str(quote_time) if quote_time else None,
        }
        return EvidenceEnvelope(
            evidence_id=uuid.uuid4().hex,
            run_id=run_id,
            capability=capability,
            symbol=symbol,
            trade_date=trade_date,
            as_of=fetched_at if quote is not None else datetime.combine(trade_date, datetime.min.time()),
            fetched_at=fetched_at,
            status=status,
            provider=provider,
            source_chain=[provider] if provider else [],
            fallback_trace=[],
            is_stale=None,
            stale_seconds=None,
            missing_fields=[],
            issues=issues,
            payload=payload,
        )

    def _normalize_daily_frame(self, df: pd.DataFrame, trade_date: date) -> Dict[str, Any]:
        frame = df.copy()
        columns = {str(column).lower(): column for column in frame.columns}
        date_column = columns.get("date") or columns.get("trade_date")
        provider_column = columns.get("data_source") or columns.get("source") or columns.get("provider")
        provider = None
        if provider_column and not frame.empty:
            provider_values = frame[provider_column].dropna()
            provider = str(provider_values.iloc[-1]) if not provider_values.empty else None

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
                    severity=EvidenceIssueSeverity.BLOCKING,
                    capability="market_daily_bars",
                    provider=provider,
                    message="日线 OHLC 存在空值或非正数",
                    observed={"trade_date": row_date.isoformat()},
                ))
                continue
            if low > min(open_price, close) or high < max(open_price, close):
                issues.append(EvidenceIssue(
                    code="provider_invalid_payload",
                    severity=EvidenceIssueSeverity.BLOCKING,
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
                "pct_change": self._pct_change(row, columns),
            })
        return {"rows": rows, "provider": provider, "issues": issues}

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
