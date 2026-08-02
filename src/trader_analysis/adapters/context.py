"""Optional DSA evidence adapters used by the TradingAgents analysts."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Callable, Optional

from data_provider.base import DataFetcherManager
from src.core.trading_calendar import get_effective_trading_date
from src.trader_analysis.adapters.browser_reader import CommunityPageReader
from src.trader_analysis.schemas.evidence import (
    EvidenceEnvelope,
    EvidenceIssue,
    EvidenceIssueSeverity,
    EvidenceStatus,
)


class ContextEvidenceAdapter:
    """Collect fundamentals and news through DSA's existing fallback layers."""

    def __init__(
        self,
        manager: Optional[DataFetcherManager] = None,
        search_service: Any = None,
        page_reader: Optional[CommunityPageReader] = None,
        now_provider: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.manager = manager or DataFetcherManager()
        self.search_service = search_service
        self.page_reader = page_reader
        self.now_provider = now_provider

    def fetch_fundamentals(self, *, run_id: str, symbol: str, trade_date: date, timeout: float) -> EvidenceEnvelope:
        try:
            payload = self.manager.get_fundamental_context(symbol, budget_seconds=timeout)
        except Exception as exc:
            return self._unavailable(run_id, "fundamentals", symbol, trade_date, exc)
        payload = dict(payload or {})
        report_date = self._fundamental_report_date(payload)
        fetched_at = self.now_provider()
        payload["report_date"] = report_date.isoformat() if report_date else None
        payload["fetched_at"] = fetched_at.isoformat()
        status = str((payload or {}).get("status") or "failed")
        usable = status in {"ok", "partial"} and any(
            isinstance((payload or {}).get(key), dict) and (payload or {}).get(key, {}).get("data")
            for key in ("valuation", "growth", "earnings", "institution", "capital_flow", "boards")
        )
        missing_fields = self._fundamental_missing_fields(payload)
        issues: list[EvidenceIssue] = []
        evidence_status = EvidenceStatus.OK
        if not usable:
            issues.append(self._issue("fundamentals_unavailable", "fundamentals", "财务证据不可用，基本面报告将被阻止"))
            evidence_status = EvidenceStatus.UNAVAILABLE
        elif report_date and (trade_date - report_date).days > 365:
            issues.append(self._issue(
                "fundamentals_report_expired",
                "fundamentals",
                f"最近一期财报（{report_date.isoformat()}）距分析日期已超过一年",
                blocking=False,
            ))
            evidence_status = EvidenceStatus.UNAVAILABLE
        elif report_date is None:
            issues.append(self._issue(
                "fundamentals_report_date_missing",
                "fundamentals",
                "已取得基本面数据，但缺少财报报告期，按部分可用处理",
                blocking=False,
            ))
            evidence_status = EvidenceStatus.PARTIAL
        elif status == "partial" or payload.get("errors") or missing_fields:
            issues.append(self._issue(
                "fundamentals_partial",
                "fundamentals",
                f"最近一期财报为 {report_date.isoformat()}，部分基本面字段缺失",
                blocking=False,
            ))
            evidence_status = EvidenceStatus.PARTIAL
        providers = self._providers(payload)
        envelope = self._envelope(
            run_id, "fundamentals", symbol, trade_date,
            evidence_status,
            providers[0] if providers else None, payload or {}, issues, providers,
            as_of=datetime.combine(report_date, datetime.min.time()) if report_date else None,
        )
        envelope.missing_fields = missing_fields
        return envelope

    @staticmethod
    def _fundamental_report_date(payload: dict) -> Optional[date]:
        earnings = payload.get("earnings") if isinstance(payload.get("earnings"), dict) else {}
        earnings_data = earnings.get("data") if isinstance(earnings.get("data"), dict) else earnings
        financial_report = (
            earnings_data.get("financial_report")
            if isinstance(earnings_data.get("financial_report"), dict)
            else {}
        )
        candidates = (
            payload.get("report_date"),
            financial_report.get("report_date"),
            earnings_data.get("report_date"),
        )
        for value in candidates:
            text = str(value or "").strip()
            if not text:
                continue
            for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
                try:
                    return datetime.strptime(text[:10], fmt).date()
                except ValueError:
                    continue
        return None

    @staticmethod
    def _fundamental_missing_fields(payload: dict) -> list[str]:
        fields = [str(item) for item in payload.get("missing_fields", []) if str(item).strip()]
        reasons = payload.get("missing_reasons")
        if isinstance(reasons, dict):
            fields.extend(str(key) for key in reasons if str(key).strip())
        return list(dict.fromkeys(fields))

    def fetch_news(self, *, run_id: str, symbol: str, name: str, trade_date: date) -> EvidenceEnvelope:
        now = self.now_provider()
        latest_completed_session = get_effective_trading_date("cn", current_time=now)
        if trade_date < latest_completed_session:
            return self._envelope(
                run_id, "news", symbol, trade_date, EvidenceStatus.UNAVAILABLE, None, {},
                [self._issue(
                    "historical_news_not_point_in_time",
                    "news",
                    "当前新闻检索按运行时窗口查询，历史分析不会读取未来新闻",
                    blocking=False,
                )], [],
            )
        try:
            if self.search_service is None:
                from src.search_service import get_search_service

                service = get_search_service()
            else:
                service = self.search_service
            response = service.search_stock_news(symbol, name or symbol, max_results=10)
            results = list(getattr(response, "results", None) or [])
            items = [
                {
                    "title": str(getattr(item, "title", "")),
                    "snippet": str(getattr(item, "snippet", "")),
                    "search_snippet": str(getattr(item, "snippet", "")),
                    "url": str(getattr(item, "url", "")),
                    "source": str(getattr(item, "source", "")),
                    "published_date": getattr(item, "published_date", None),
                    "fetched_at": now.isoformat(),
                    "content_kind": "search_snippet",
                }
                for item in results
            ]
            if self.page_reader is not None:
                items = self.page_reader.enrich_items(items, run_id=run_id)
            payload = {
                "query": getattr(response, "query", ""),
                "items": items,
            }
            provider = str(getattr(response, "provider", "") or "") or None
            success = bool(getattr(response, "success", False)) and bool(results)
        except Exception as exc:
            return self._unavailable(run_id, "news", symbol, trade_date, exc)
        issues = [] if success else [self._issue("news_unavailable", "news", "未取得可核验的个股新闻", blocking=False)]
        if success and trade_date < now.date():
            issues.append(self._issue(
                "runtime_news_not_point_in_time",
                "news",
                "新闻按本次运行时间检索，用于最近交易日分析，但不代表历史时点快照",
                blocking=False,
            ))
        return self._envelope(
            run_id, "news", symbol, trade_date,
            EvidenceStatus.PARTIAL if success and issues else EvidenceStatus.OK if success else EvidenceStatus.UNAVAILABLE,
            provider, payload, issues, [provider] if provider else [],
        )

    def fetch_sentiment(
        self, *, run_id: str, symbol: str, name: str, trade_date: date,
    ) -> EvidenceEnvelope:
        """Collect community opinion independently from company news."""
        now = self.now_provider()
        latest_completed_session = get_effective_trading_date("cn", current_time=now)
        if trade_date < latest_completed_session:
            return self._envelope(
                run_id, "sentiment", symbol, trade_date, EvidenceStatus.UNAVAILABLE, None, {},
                [self._issue(
                    "historical_sentiment_not_point_in_time", "sentiment",
                    "社区检索按运行时间查询，历史分析不使用未快照的当前讨论",
                    blocking=False,
                )], [],
            )
        try:
            if self.search_service is None:
                from src.search_service import get_search_service

                service = get_search_service()
            else:
                service = self.search_service
            response = service.search_community_sentiment(symbol, name or symbol, max_results=10)
            results = list(getattr(response, "results", None) or [])
            items = [
                {
                    "title": str(getattr(item, "title", "")),
                    "snippet": str(getattr(item, "snippet", "")),
                    "search_snippet": str(getattr(item, "snippet", "")),
                    "url": str(getattr(item, "url", "")),
                    "source": str(getattr(item, "source", "")),
                    "published_date": getattr(item, "published_date", None),
                    "fetched_at": now.isoformat(),
                    "content_kind": "search_snippet",
                }
                for item in results
            ]
            if self.page_reader is not None:
                items = self.page_reader.enrich_items(items, run_id=run_id)
            provider = str(getattr(response, "provider", "") or "") or None
            success = bool(getattr(response, "success", False)) and bool(items)
        except Exception as exc:
            return self._unavailable(run_id, "sentiment", symbol, trade_date, exc)
        issues = [] if success else [self._issue(
            "community_sentiment_unavailable", "sentiment",
            "未取得可核验的投资社区观点；不使用新闻充当社区情绪",
            blocking=False,
        )]
        if success and trade_date < now.date():
            issues.append(self._issue(
                "runtime_sentiment_not_point_in_time", "sentiment",
                "社区观点按本次运行时间检索，不代表历史时点快照",
                blocking=False,
            ))
        return self._envelope(
            run_id, "sentiment", symbol, trade_date,
            EvidenceStatus.PARTIAL if success and issues else EvidenceStatus.OK if success else EvidenceStatus.UNAVAILABLE,
            provider, {"query": getattr(response, "query", ""), "social_items": items},
            issues, [provider] if provider else [],
        )

    @staticmethod
    def _providers(payload: Any) -> list[str]:
        providers: list[str] = []
        for item in (payload or {}).get("source_chain", []):
            value = item.get("provider") if isinstance(item, dict) else item
            value = str(value or "").strip()
            if value and value not in providers:
                providers.append(value)
        return providers

    @staticmethod
    def _issue(code: str, capability: str, message: str, *, blocking: bool = True) -> EvidenceIssue:
        return EvidenceIssue(
            code=code,
            severity=EvidenceIssueSeverity.BLOCKING if blocking else EvidenceIssueSeverity.WARNING,
            capability=capability,
            message=message,
        )

    def _unavailable(self, run_id: str, capability: str, symbol: str, trade_date: date, exc: Exception) -> EvidenceEnvelope:
        return self._envelope(
            run_id, capability, symbol, trade_date, EvidenceStatus.UNAVAILABLE, None, {},
            [EvidenceIssue(
                code=f"{capability}_provider_error",
                severity=EvidenceIssueSeverity.WARNING,
                capability=capability,
                message=f"{capability} 数据源调用失败",
                observed={"error_type": type(exc).__name__},
                retriable=True,
            )], [],
        )

    @staticmethod
    def _envelope(
        run_id: str, capability: str, symbol: str, trade_date: date,
        status: EvidenceStatus, provider: Optional[str], payload: dict,
        issues: list[EvidenceIssue], source_chain: list[str],
        as_of: Optional[datetime] = None,
    ) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_id=uuid.uuid4().hex,
            run_id=run_id,
            capability=capability,
            symbol=symbol,
            trade_date=trade_date,
            as_of=as_of or datetime.combine(trade_date, datetime.min.time()),
            fetched_at=datetime.now(),
            status=status,
            provider=provider,
            source_chain=source_chain,
            issues=issues,
            payload=payload,
        )
