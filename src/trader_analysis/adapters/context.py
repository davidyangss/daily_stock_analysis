"""Optional DSA evidence adapters used by the TradingAgents analysts."""

from __future__ import annotations

import copy
import re
import uuid
from datetime import date, datetime
from typing import Any, Callable, Optional
from urllib.parse import urlparse

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
        # The manager may return a cached mapping.  Never mutate shared cached
        # evidence while applying a run-specific point-in-time cutoff.
        payload = copy.deepcopy(payload or {})
        self._separate_mixed_financial_periods(payload)
        fetched_at = self.now_provider()
        latest_completed_session = get_effective_trading_date("cn", current_time=fetched_at)
        historical_cutoff = trade_date < latest_completed_session
        point_in_time = self._constrain_fundamentals(
            payload,
            trade_date=trade_date,
            strict=historical_cutoff,
        )
        report_date = self._fundamental_report_date(payload)
        announcement_date = self._fundamental_announcement_date(payload)
        available_date = self._fundamental_available_date(payload)
        payload["report_date"] = report_date.isoformat() if report_date else None
        payload["announcement_date"] = announcement_date.isoformat() if announcement_date else None
        payload["available_at"] = available_date.isoformat() if available_date else None
        payload["fetched_at"] = fetched_at.isoformat()
        payload["point_in_time"] = {
            "cutoff_date": trade_date.isoformat(),
            "mode": "historical_strict" if historical_cutoff else "runtime_latest_session",
            "status": point_in_time["status"],
            "removed_blocks": point_in_time["removed_blocks"],
            "removed_reports": point_in_time["removed_reports"],
        }
        status = str((payload or {}).get("status") or "failed")
        usable = status in {"ok", "partial"} and any(
            isinstance((payload or {}).get(key), dict) and (payload or {}).get(key, {}).get("data")
            for key in ("valuation", "growth", "earnings", "institution", "capital_flow", "boards")
        )
        missing_fields = self._fundamental_missing_fields(payload)
        issues: list[EvidenceIssue] = []
        evidence_status = EvidenceStatus.OK
        if not usable:
            code = (
                "historical_fundamentals_not_point_in_time"
                if historical_cutoff
                else "fundamentals_unavailable"
            )
            message = (
                "现有财务记录无法证明在分析日已经公告，历史分析不使用运行时基本面回填"
                if historical_cutoff
                else "财务证据不可用，基本面分析将明确披露缺失并降级"
            )
            issues.append(self._issue(code, "fundamentals", message, blocking=False))
            evidence_status = EvidenceStatus.UNAVAILABLE
        elif report_date and (trade_date - report_date).days > 365:
            issues.append(self._issue(
                "fundamentals_report_expired",
                "fundamentals",
                f"最近一期财报（{report_date.isoformat()}）距分析日期已超过一年",
                blocking=False,
            ))
            evidence_status = EvidenceStatus.UNAVAILABLE
        else:
            if report_date is None:
                issues.append(self._issue(
                    "fundamentals_report_date_missing",
                    "fundamentals",
                    "已取得基本面数据，但缺少财报报告期，按部分可用处理",
                    blocking=False,
                ))
            if not historical_cutoff:
                issues.append(self._issue(
                    "fundamentals_runtime_snapshot",
                    "fundamentals",
                    "基本面按本次运行时间聚合；报告期和公告日已披露，但运行时估值、资金与板块数据不代表历史快照",
                    blocking=False,
                ))
            if status == "partial" or payload.get("errors") or missing_fields:
                issues.append(self._issue(
                    "fundamentals_partial",
                    "fundamentals",
                    (
                        f"最近一期财报为 {report_date.isoformat()}，部分基本面字段缺失"
                        if report_date
                        else "部分基本面字段缺失"
                    ),
                    blocking=False,
                ))
            if issues:
                evidence_status = EvidenceStatus.PARTIAL
        providers = self._providers(payload)
        envelope = self._envelope(
            run_id, "fundamentals", symbol, trade_date,
            evidence_status,
            providers[0] if providers else None, payload or {}, issues, providers,
            as_of=datetime.combine(
                available_date or announcement_date or report_date,
                datetime.min.time(),
            ) if available_date or announcement_date or report_date else None,
            fetched_at=fetched_at,
        )
        envelope.missing_fields = missing_fields
        return envelope

    @classmethod
    def _constrain_fundamentals(
        cls,
        payload: dict,
        *,
        trade_date: date,
        strict: bool,
    ) -> dict[str, Any]:
        """Apply a fail-closed historical cutoff without changing provider code.

        The current fundamental pipeline combines statement data with runtime
        valuation, capital-flow, institution and board snapshots.  For an old
        trade date those blocks cannot be made point-in-time merely by checking
        the statement report period, so they are removed.  A statement remains
        usable only when its explicit announcement/availability date is on or
        before the requested trade date.
        """
        if not strict:
            return {"status": "runtime_snapshot", "removed_blocks": [], "removed_reports": []}

        removed_blocks: list[str] = []
        removed_reports: list[dict[str, Any]] = []
        earnings = payload.get("earnings") if isinstance(payload.get("earnings"), dict) else {}
        earnings_data = earnings.get("data") if isinstance(earnings.get("data"), dict) else earnings
        primary = earnings_data.get("financial_report")
        supplemental = earnings_data.get("supplemental_financial_reports")
        reports = ([primary] if isinstance(primary, dict) else []) + (
            [item for item in supplemental if isinstance(item, dict)]
            if isinstance(supplemental, list) else []
        )

        admitted: list[dict[str, Any]] = []
        primary_admitted = False
        for report in reports:
            report_date = cls._parse_date(report.get("report_date"))
            available_date = cls._report_available_date(report)
            if (
                report_date is not None
                and report_date <= trade_date
                and available_date is not None
                and available_date <= trade_date
            ):
                admitted.append(report)
                primary_admitted = primary_admitted or report is primary
                continue
            if report_date is None:
                reason = "report_date_missing"
            elif report_date > trade_date:
                reason = "report_period_after_cutoff"
            elif available_date is None:
                reason = "announcement_date_missing"
            else:
                reason = "not_available_at_cutoff"
            announced_date = cls._parse_date(
                report.get("announcement_date") or report.get("ann_date")
            )
            explicit_available_date = cls._parse_date(report.get("available_at"))
            removed_reports.append({
                "report_date": report_date.isoformat() if report_date else None,
                "announcement_date": announced_date.isoformat() if announced_date else None,
                "available_at": (
                    explicit_available_date.isoformat() if explicit_available_date else None
                ),
                "admission_date": available_date.isoformat() if available_date else None,
                "reason": reason,
            })

        def report_order(item: dict[str, Any]) -> tuple[date, date]:
            return (
                cls._parse_date(item.get("report_date")) or date.min,
                cls._report_available_date(item) or date.min,
            )

        if admitted:
            # Preserve the provider's primary statement when it passed the
            # cutoff so the sibling growth block keeps referring to the same
            # period. A newer forecast remains a supplemental record and must
            # not silently become the statement that growth metrics describe.
            chosen_primary = primary if primary_admitted else max(admitted, key=report_order)
            earnings_data["financial_report"] = chosen_primary
            earnings_data["supplemental_financial_reports"] = sorted(
                [item for item in admitted if item is not chosen_primary],
                key=report_order,
                reverse=True,
            )
            # Other earnings summaries and TTM dividend calculations are
            # runtime aggregates without a uniform availability timestamp.
            for key in list(earnings_data):
                if key not in {"financial_report", "supplemental_financial_reports"}:
                    earnings_data.pop(key, None)
            earnings["status"] = "ok"
            if isinstance(earnings.get("coverage"), dict):
                earnings["coverage"]["status"] = "ok"
        else:
            earnings_data.clear()
            earnings["status"] = "not_supported"
            if isinstance(earnings.get("coverage"), dict):
                earnings["coverage"]["status"] = "not_supported"

        # Growth metrics describe the original primary statement.  They are
        # safe only when that exact primary report passed the cutoff.
        if not primary_admitted:
            cls._clear_fundamental_block(payload, "growth", "point_in_time_unverifiable")
            removed_blocks.append("growth")

        for block_name in (
            "valuation", "institution", "capital_flow", "dragon_tiger", "boards",
        ):
            block = payload.get(block_name)
            if isinstance(block, dict) and block.get("data"):
                removed_blocks.append(block_name)
            cls._clear_fundamental_block(payload, block_name, "runtime_only_for_historical_cutoff")

        usable_blocks = []
        for block_name in ("growth", "earnings"):
            block = payload.get(block_name)
            if isinstance(block, dict) and block.get("data"):
                usable_blocks.append(block_name)
        retained_source_chain: list[Any] = []
        retained_errors: list[str] = []
        for block_name in usable_blocks:
            block = payload[block_name]
            for item in block.get("source_chain", []):
                if item not in retained_source_chain:
                    retained_source_chain.append(item)
            for item in block.get("errors", []):
                text = str(item)
                if text and text not in retained_errors:
                    retained_errors.append(text)
        payload["source_chain"] = retained_source_chain
        payload["errors"] = retained_errors
        payload["status"] = "ok" if usable_blocks else "failed"
        payload["coverage"] = {
            key: (
                str(value.get("status") or "not_supported")
                if isinstance(value, dict) else "not_supported"
            )
            for key, value in payload.items()
            if key in {
                "valuation", "growth", "earnings", "institution", "capital_flow",
                "dragon_tiger", "boards",
            }
        }
        return {
            "status": "point_in_time" if usable_blocks else "unavailable",
            "removed_blocks": removed_blocks,
            "removed_reports": removed_reports,
        }

    @staticmethod
    def _clear_fundamental_block(payload: dict, name: str, reason: str) -> None:
        block = payload.get(name)
        if not isinstance(block, dict):
            payload[name] = {
                "status": "not_supported", "coverage": {"status": "not_supported"},
                "source_chain": [], "errors": [reason], "data": {},
            }
            return
        block["status"] = "not_supported"
        block["data"] = {}
        coverage = block.get("coverage")
        if isinstance(coverage, dict):
            coverage["status"] = "not_supported"
        errors = block.setdefault("errors", [])
        if isinstance(errors, list) and reason not in errors:
            errors.append(reason)

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        if not text:
            return None
        normalized = text[:10].replace("/", "-")
        for candidate, fmt in ((normalized, "%Y-%m-%d"), (re.sub(r"\D", "", text)[:8], "%Y%m%d")):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
        return None

    @classmethod
    def _report_available_date(cls, report: dict) -> Optional[date]:
        # ``available_at`` is the strongest point-in-time admission field: it
        # records when this exact payload first became usable.  A provider may
        # also expose an earlier, date-only announcement label, which must not
        # override a later explicit availability timestamp.
        for key in ("available_at", "announcement_date", "ann_date"):
            if parsed := cls._parse_date(report.get(key)):
                return parsed
        return None

    @staticmethod
    def _separate_mixed_financial_periods(payload: dict) -> None:
        """Split provider fields by both report period and disclosure type."""
        earnings = payload.get("earnings") if isinstance(payload.get("earnings"), dict) else {}
        earnings_data = earnings.get("data") if isinstance(earnings.get("data"), dict) else earnings
        report = earnings_data.get("financial_report")
        if not isinstance(report, dict):
            return
        field_periods = report.get("field_periods")
        if not isinstance(field_periods, dict):
            return
        field_report_types = report.get("field_report_types")
        if not isinstance(field_report_types, dict):
            field_report_types = {}
        field_announcement_dates = report.get("field_announcement_dates")
        if not isinstance(field_announcement_dates, dict):
            field_announcement_dates = {}
        field_sources = report.get("field_sources")
        if not isinstance(field_sources, dict):
            field_sources = {}

        def normalize_period(value: Any) -> str:
            digits = re.sub(r"\D", "", str(value or ""))
            if len(digits) != 8:
                return ""
            try:
                return datetime.strptime(digits, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                return ""

        value_fields = (
            "revenue", "net_profit_parent", "operating_cash_flow", "roe",
            "revenue_yoy", "net_profit_yoy", "gross_margin",
        )
        grouped: dict[tuple[str, str], dict] = {}
        for field in value_fields:
            value = report.get(field)
            period = normalize_period(field_periods.get(field))
            if value is None or not period:
                continue
            report_type = str(field_report_types.get(field) or "").strip()
            key = (period, report_type)
            period_report = grouped.setdefault(
                key, {"report_date": period, "field_periods": {}},
            )
            period_report[field] = value
            period_report["field_periods"][field] = period
            if report_type:
                period_report.setdefault("field_report_types", {})[field] = report_type
            announcement_date = field_announcement_dates.get(field)
            if announcement_date not in (None, ""):
                period_report.setdefault("field_announcement_dates", {})[field] = announcement_date
            source = field_sources.get(field)
            if source not in (None, ""):
                period_report.setdefault("field_sources", {})[field] = source
        if not grouped:
            return

        primary_period = normalize_period(report.get("report_date"))
        declared_type = str(report.get("report_type") or "").strip()
        if declared_type in {"unclassified_period_data", ""}:
            declared_type = ""

        primary_key: Optional[tuple[str, str]] = None
        primary_candidates = [key for key in grouped if key[0] == primary_period]
        if declared_type and (primary_period, declared_type) in grouped:
            primary_key = (primary_period, declared_type)
        elif (primary_period, "financial_statement") in grouped:
            primary_key = (primary_period, "financial_statement")
        elif len(primary_candidates) == 1:
            primary_key = primary_candidates[0]

        primary = grouped.pop(primary_key, None) if primary_key else None
        if primary is None:
            primary = {"report_date": primary_period or None, "field_periods": {}}

        metadata_maps = {
            "field_periods", "field_report_types", "field_announcement_dates", "field_sources",
        }
        for key, value in report.items():
            if key in value_fields or key in metadata_maps or key in {
                "report_type", "period_consistency", "data_basis",
            }:
                continue
            # A report-level announcement/document label from a mixed payload
            # must not be copied onto a field group with unknown provenance.
            if key in {"announcement_date", "available_at", "ann_date", "document_type"}:
                continue
            primary.setdefault(key, value)

        def finalize(period_report: dict, *, separated: bool, is_primary: bool) -> None:
            explicit_types = {
                str(value).strip()
                for value in period_report.get("field_report_types", {}).values()
                if str(value).strip()
            }
            if len(explicit_types) == 1:
                resolved_type = next(iter(explicit_types))
                period_report["report_type"] = resolved_type
                period_report["period_consistency"] = (
                    "separated_from_mixed_provider_payload" if separated else "consistent"
                )
            elif explicit_types:
                period_report["report_type"] = "unclassified_period_data"
                period_report["period_consistency"] = "mixed_disclosure_types"
            elif is_primary and declared_type and any(
                period_report.get(field) is not None for field in value_fields
            ):
                period_report["report_type"] = declared_type
                period_report["period_consistency"] = (
                    "separated_from_mixed_provider_payload" if separated else "consistent"
                )
            elif any(period_report.get(field) is not None for field in value_fields):
                period_report["report_type"] = "unclassified_period_data"
                period_report["period_consistency"] = "period_consistent_disclosure_type_unverified"
            else:
                period_report["report_type"] = declared_type or "unclassified_period_data"
                period_report["period_consistency"] = "declared_period_without_attributed_values"

            announcements = {
                normalize_period(value)
                for value in period_report.get("field_announcement_dates", {}).values()
                if normalize_period(value)
            }
            if len(announcements) == 1:
                period_report["announcement_date"] = next(iter(announcements))
                period_report["available_at"] = period_report["announcement_date"]
            elif (
                period_report["report_type"] in {"financial_statement", "earnings_forecast"}
                and not is_primary
            ):
                # In legacy mixed payloads a single report-level date usually
                # belongs to the explicitly typed supplemental disclosure.
                for metadata_key in ("announcement_date", "available_at", "ann_date"):
                    if report.get(metadata_key) not in (None, ""):
                        period_report.setdefault(metadata_key, report[metadata_key])
            elif len(grouped) == 0 and is_primary:
                for metadata_key in ("announcement_date", "available_at", "ann_date"):
                    if report.get(metadata_key) not in (None, ""):
                        period_report.setdefault(metadata_key, report[metadata_key])

            if period_report["report_type"] == declared_type:
                if report.get("document_type") not in (None, ""):
                    period_report.setdefault("document_type", report["document_type"])
                if report.get("data_basis") not in (None, ""):
                    period_report.setdefault("data_basis", report["data_basis"])

        finalize(primary, separated=bool(grouped), is_primary=True)
        earnings_data["financial_report"] = primary
        supplemental = earnings_data.setdefault("supplemental_financial_reports", [])
        if isinstance(supplemental, list):
            for period_report in grouped.values():
                if report.get("currency") not in (None, ""):
                    period_report.setdefault("currency", report["currency"])
                finalize(period_report, separated=True, is_primary=False)
                if period_report not in supplemental:
                    supplemental.append(period_report)

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
            financial_report.get("report_date"),
            payload.get("report_date"),
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

    @classmethod
    def _fundamental_announcement_date(cls, payload: dict) -> Optional[date]:
        earnings = payload.get("earnings") if isinstance(payload.get("earnings"), dict) else {}
        earnings_data = earnings.get("data") if isinstance(earnings.get("data"), dict) else earnings
        financial_report = (
            earnings_data.get("financial_report")
            if isinstance(earnings_data.get("financial_report"), dict)
            else {}
        )
        return cls._parse_date(
            financial_report.get("announcement_date") or financial_report.get("ann_date")
        )

    @classmethod
    def _fundamental_available_date(cls, payload: dict) -> Optional[date]:
        earnings = payload.get("earnings") if isinstance(payload.get("earnings"), dict) else {}
        earnings_data = earnings.get("data") if isinstance(earnings.get("data"), dict) else earnings
        financial_report = (
            earnings_data.get("financial_report")
            if isinstance(earnings_data.get("financial_report"), dict)
            else {}
        )
        return cls._report_available_date(financial_report)

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
                self._search_item(
                    item,
                    search_provider=str(getattr(response, "provider", "") or ""),
                    fetched_at=now,
                )
                for item in results
            ]
            if self.page_reader is not None:
                items = self.page_reader.enrich_items(items, run_id=run_id)
            payload = {
                "query": getattr(response, "query", ""),
                "search_provider": str(getattr(response, "provider", "") or "") or None,
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
            as_of=self._items_as_of(items), fetched_at=now,
        )

    @staticmethod
    def _search_item(item: Any, *, search_provider: str, fetched_at: datetime) -> dict[str, Any]:
        url = str(getattr(item, "url", "") or "")
        publisher = str(getattr(item, "source", "") or "")
        published = getattr(item, "published_date", None)
        return {
            "title": str(getattr(item, "title", "")),
            "snippet": str(getattr(item, "snippet", "")),
            "search_snippet": str(getattr(item, "snippet", "")),
            "url": url,
            # Keep the legacy source field for report compatibility,
            # while making publisher and retrieval provider distinct.
            "source": publisher,
            "publisher": publisher or None,
            "search_provider": search_provider or None,
            "source_domain": urlparse(url).netloc.lower().split(":", 1)[0] or None,
            "published_date": published,
            "published_at_status": "provided" if published else "undated",
            "fetched_at": fetched_at.isoformat(),
            "content_kind": "search_snippet",
        }

    @classmethod
    def _items_as_of(cls, items: list[dict[str, Any]]) -> Optional[datetime]:
        published_dates = [
            parsed
            for item in items
            if (parsed := cls._parse_date(item.get("published_date"))) is not None
        ]
        return (
            datetime.combine(max(published_dates), datetime.min.time())
            if published_dates else None
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
            response = service.search_community_sentiment(symbol, name or symbol, max_results=10, days=7)
            results = list(getattr(response, "results", None) or [])
            items = [
                self._search_item(
                    item,
                    search_provider=str(getattr(response, "provider", "") or ""),
                    fetched_at=now,
                )
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
            provider, {
                "query": getattr(response, "query", ""),
                "search_provider": provider,
                "window_days": 7,
                "social_items": items,
            },
            issues, [provider] if provider else [],
            as_of=self._items_as_of(items), fetched_at=now,
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

    def _envelope(
        self,
        run_id: str, capability: str, symbol: str, trade_date: date,
        status: EvidenceStatus, provider: Optional[str], payload: dict,
        issues: list[EvidenceIssue], source_chain: list[str],
        as_of: Optional[datetime] = None,
        fetched_at: Optional[datetime] = None,
    ) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_id=uuid.uuid4().hex,
            run_id=run_id,
            capability=capability,
            symbol=symbol,
            trade_date=trade_date,
            as_of=as_of,
            fetched_at=fetched_at or self.now_provider(),
            status=status,
            provider=provider,
            source_chain=source_chain,
            issues=issues,
            payload=payload,
        )
