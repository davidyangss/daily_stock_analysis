"""Optional DSA evidence adapters used by the TradingAgents analysts."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Callable, Optional

from data_provider.base import DataFetcherManager
from src.core.trading_calendar import get_effective_trading_date
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
        now_provider: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.manager = manager or DataFetcherManager()
        self.search_service = search_service
        self.now_provider = now_provider

    def fetch_fundamentals(self, *, run_id: str, symbol: str, trade_date: date, timeout: float) -> EvidenceEnvelope:
        if trade_date < date.today():
            return self._envelope(
                run_id, "fundamentals", symbol, trade_date, EvidenceStatus.UNAVAILABLE, None, {},
                [self._issue(
                    "historical_fundamentals_not_point_in_time",
                    "fundamentals",
                    "DSA 财务数据尚无可核验公告可得日期，历史分析不会读取当前财务数据",
                    blocking=False,
                )], [],
            )
        try:
            payload = self.manager.get_fundamental_context(symbol, budget_seconds=timeout)
        except Exception as exc:
            return self._unavailable(run_id, "fundamentals", symbol, trade_date, exc)
        status = str((payload or {}).get("status") or "failed")
        usable = status in {"ok", "partial"} and any(
            isinstance((payload or {}).get(key), dict) and (payload or {}).get(key, {}).get("data")
            for key in ("valuation", "growth", "earnings", "institution", "capital_flow", "boards")
        )
        issues = []
        if not usable:
            issues.append(self._issue("fundamentals_unavailable", "fundamentals", "财务证据不可用，基本面报告将被阻止"))
        elif status == "partial" or (payload or {}).get("errors"):
            issues.append(self._issue("fundamentals_partial", "fundamentals", "财务证据不完整，报告必须披露缺失项", blocking=False))
        providers = self._providers(payload)
        return self._envelope(
            run_id, "fundamentals", symbol, trade_date,
            EvidenceStatus.OK if usable and not issues else EvidenceStatus.PARTIAL if usable else EvidenceStatus.UNAVAILABLE,
            providers[0] if providers else None, payload or {}, issues, providers,
        )

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
            payload = {
                "query": getattr(response, "query", ""),
                "items": [
                    {
                        "title": str(getattr(item, "title", "")),
                        "snippet": str(getattr(item, "snippet", "")),
                        "url": str(getattr(item, "url", "")),
                        "source": str(getattr(item, "source", "")),
                        "published_date": getattr(item, "published_date", None),
                        "fetched_at": now.isoformat(),
                    }
                    for item in results
                ],
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
                    "url": str(getattr(item, "url", "")),
                    "source": str(getattr(item, "source", "")),
                    "published_date": getattr(item, "published_date", None),
                    "fetched_at": now.isoformat(),
                }
                for item in results
            ]
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
    ) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_id=uuid.uuid4().hex,
            run_id=run_id,
            capability=capability,
            symbol=symbol,
            trade_date=trade_date,
            as_of=datetime.combine(trade_date, datetime.min.time()),
            fetched_at=datetime.now(),
            status=status,
            provider=provider,
            source_chain=source_chain,
            issues=issues,
            payload=payload,
        )
