"""Run-scoped TradingAgents tools backed only by canonical DSA evidence."""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import date, datetime
from functools import wraps
from typing import Any, Callable, Sequence

import pandas as pd

from src.trader_analysis.schemas.evidence import EvidenceEnvelope, EvidenceLedger, EvidenceStatus


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, indent=2)


class DsaTradingAgentsToolkit:
    """Build matching analyst/tool-node tools for one immutable run ledger."""

    def __init__(self, ledger: EvidenceLedger, trace_emit=None) -> None:
        self.ledger = ledger
        self.symbol = ledger.symbol
        self._tools: dict[str, Any] = {}
        self.trace_emit = trace_emit
        self._consumed_capabilities: set[str] = set()
        self._consumed_lock = threading.Lock()

    @property
    def consumed_capabilities(self) -> set[str]:
        """Return the canonical evidence capabilities actually requested by tools."""
        with self._consumed_lock:
            return set(self._consumed_capabilities)

    def _require_symbol(self, ticker: str) -> None:
        normalized = str(ticker).upper().replace("SH", "").replace("SZ", "").replace("BJ", "").split(".")[0]
        if normalized != self.symbol:
            raise ValueError(f"tool symbol mismatch: expected {self.symbol}, got {ticker}")

    def _envelope(self, capability: str) -> EvidenceEnvelope:
        envelope = self.ledger.envelopes.get(capability)
        if envelope is None:
            raise ValueError(f"canonical evidence unavailable: {capability}")
        with self._consumed_lock:
            self._consumed_capabilities.add(capability)
        if self.trace_emit:
            self.trace_emit(
                event_type="evidence.consumed", stage="tool", payload={
                    "capability": capability,
                    "evidence_id": envelope.evidence_id,
                    "provider": envelope.provider,
                    "status": envelope.status.value,
                    "as_of": envelope.as_of,
                },
            )
        return envelope

    def get_stock_data(self, ticker: str, start_date: str, end_date: str) -> str:
        self._require_symbol(ticker)
        rows = list((self._envelope("market_daily_bars").payload or {}).get("rows") or [])
        selected = [row for row in rows if start_date <= str(row.get("trade_date", "")) <= end_date]
        if not selected:
            return "NO_DATA_AVAILABLE: requested date range has no verified DSA daily bars."
        return pd.DataFrame(selected).rename(
            columns={"volume_shares": "volume", "amount_cny": "amount"}
        ).to_csv(index=False)

    def get_indicators(self, ticker: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
        self._require_symbol(ticker)
        rows = list((self._envelope("market_daily_bars").payload or {}).get("rows") or [])
        frame = pd.DataFrame(rows)
        if frame.empty or "close" not in frame:
            return "NO_DATA_AVAILABLE: verified daily bars are unavailable."
        close = pd.to_numeric(frame["close"], errors="coerce")
        name = indicator.lower()
        if name == "close_50_sma":
            values = close.rolling(50).mean()
        elif name == "close_200_sma":
            values = close.rolling(200).mean()
        elif name == "close_10_ema":
            values = close.ewm(span=10, adjust=False).mean()
        elif name in {"macd", "macds", "macdh"}:
            dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
            dea = dif.ewm(span=9, adjust=False).mean()
            values = {"macd": dif, "macds": dea, "macdh": 2 * (dif - dea)}[name]
        elif name == "rsi":
            delta = close.diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
            values = (100 - (100 / (1 + avg_gain / avg_loss))).fillna(50)
        elif name in {"boll", "boll_ub", "boll_lb"}:
            middle = close.rolling(20).mean()
            deviation = close.rolling(20).std(ddof=0)
            values = {"boll": middle, "boll_ub": middle + 2 * deviation, "boll_lb": middle - 2 * deviation}[name]
        elif name == "atr" and {"high", "low"}.issubset(frame.columns):
            high = pd.to_numeric(frame["high"], errors="coerce")
            low = pd.to_numeric(frame["low"], errors="coerce")
            values = pd.concat([(high-low), (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1).rolling(14).mean()
        elif name == "vwma" and ({"volume", "volume_shares"} & set(frame.columns)):
            volume_column = "volume" if "volume" in frame else "volume_shares"
            volume = pd.to_numeric(frame[volume_column], errors="coerce")
            values = (close * volume).rolling(20).sum() / volume.rolling(20).sum()
        else:
            return f"NO_DATA_AVAILABLE: unsupported deterministic indicator {indicator}."
        output = pd.DataFrame({"trade_date": frame["trade_date"], indicator: values}).dropna().tail(max(1, look_back_days))
        return output.to_csv(index=False) if not output.empty else "NO_DATA_AVAILABLE: insufficient bars for indicator."

    def get_verified_market_snapshot(self, ticker: str, curr_date: str) -> str:
        self._require_symbol(ticker)
        envelope = self._envelope("verified_market_snapshot")
        return _json({"status": envelope.status.value, "provider": envelope.provider, "as_of": envelope.as_of, **(envelope.payload or {})})

    def get_news(self, ticker: str, start_date: str, end_date: str) -> str:
        self._require_symbol(ticker)
        items = list((self._envelope("news").payload or {}).get("items") or [])
        return _json(self._filter_items_by_date(items, start_date=start_date, end_date=end_date))

    def get_global_news(self, curr_date: str, look_back_days: int = 7, limit: int = 10) -> str:
        return (
            "DATA_UNAVAILABLE: 本次运行未加载具备独立来源和时点约束的 A 股宏观/全市场新闻；"
            "不得用个股新闻冒充宏观新闻或虚构市场背景。"
        )

    def get_insider_transactions(self, symbol: str) -> str:
        self._require_symbol(symbol)
        envelope = self._envelope("fundamentals")
        if envelope.status == EvidenceStatus.UNAVAILABLE:
            return _json(self._unavailable_fundamentals(envelope))
        fundamentals = envelope.payload or {}
        return _json(fundamentals.get("institution") or {"status": "unavailable"})

    def get_macro_indicators(self, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
        return "DATA_UNAVAILABLE: no point-in-time DSA macro series is configured; do not fabricate values."

    def get_prediction_markets(self, topic: str, limit: int = 10) -> str:
        return "DATA_UNAVAILABLE: prediction markets are outside the A-share phase-1 evidence contract."

    def get_fundamentals(self, ticker: str, curr_date: str | None = None) -> str:
        self._require_symbol(ticker)
        envelope = self._envelope("fundamentals")
        if envelope.status == EvidenceStatus.UNAVAILABLE:
            return _json(self._unavailable_fundamentals(envelope))
        return _json(envelope.payload or {})

    @staticmethod
    def _unavailable_fundamentals(envelope: EvidenceEnvelope) -> dict[str, Any]:
        payload = envelope.payload or {}
        return {
            "status": "unavailable",
            "report_date": payload.get("report_date"),
            "fetched_at": payload.get("fetched_at"),
            "reasons": [issue.message for issue in envelope.issues],
        }

    def get_balance_sheet(self, ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
        self._require_symbol(ticker)
        return _json(self._financial_statement_view("balance_sheet"))

    def get_cashflow(self, ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
        self._require_symbol(ticker)
        return _json(self._financial_statement_view("cash_flow"))

    def get_income_statement(self, ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
        self._require_symbol(ticker)
        return _json(self._financial_statement_view("income_statement"))

    def _financial_statement_view(self, statement: str) -> dict[str, Any]:
        envelope = self._envelope("fundamentals")
        if envelope.status == EvidenceStatus.UNAVAILABLE:
            return {"statement": statement, **self._unavailable_fundamentals(envelope)}
        payload = envelope.payload or {}
        earnings = payload.get("earnings") if isinstance(payload.get("earnings"), dict) else {}
        earnings_data = earnings.get("data") if isinstance(earnings.get("data"), dict) else earnings
        primary = earnings_data.get("financial_report")
        supplemental = earnings_data.get("supplemental_financial_reports")
        reports = ([primary] if isinstance(primary, dict) else []) + (
            [item for item in supplemental if isinstance(item, dict)]
            if isinstance(supplemental, list) else []
        )
        field_map = {
            "balance_sheet": ("total_assets", "total_liabilities", "equity_parent"),
            "cash_flow": ("operating_cash_flow",),
            "income_statement": ("revenue", "net_profit_parent"),
        }
        identity_fields = (
            "report_date", "announcement_date", "available_at", "ann_date",
            "report_type", "document_type", "currency", "period_consistency",
            "field_periods", "field_report_types",
        )
        fields = field_map[statement]
        selected = [
            {
                key: report[key]
                for key in (*identity_fields, *fields)
                if key in report and report[key] not in (None, "", {}, [])
            }
            for report in reports
        ]
        selected = [item for item in selected if any(field in item for field in fields)]
        return {
            "status": "ok" if selected else "unavailable",
            "statement": statement,
            "provider": envelope.provider,
            "as_of": envelope.as_of,
            "fetched_at": envelope.fetched_at,
            "reports": selected,
            "reason": None if selected else "requested statement fields are absent from canonical DSA evidence",
        }

    def prefetch_sentiment(self, ticker: str, start_date: str, end_date: str) -> dict[str, Any]:
        return self._trace_direct_call(
            "prefetch_sentiment",
            {"ticker": ticker, "start_date": start_date, "end_date": end_date},
            lambda: self._prefetch_sentiment(ticker, start_date, end_date),
        )

    def _prefetch_sentiment(self, ticker: str, start_date: str, end_date: str) -> dict[str, Any]:
        self._require_symbol(ticker)
        envelope = self._envelope("sentiment")
        payload = envelope.payload or {}
        social_items = self._filter_items_by_date(
            list(payload.get("social_items") or []), start_date=start_date, end_date=end_date,
        )
        news_envelope = self._envelope("news")
        news_items = self._filter_items_by_date(
            list((news_envelope.payload or {}).get("items") or []),
            start_date=start_date,
            end_date=end_date,
        )
        news_block = (
            "DSA SOURCE CONTRACT: 以下记录是国内个股新闻或公告证据。search_provider 表示检索服务，"
            "publisher/source 表示内容发布方，二者不得混称。未提供 published_date 的记录只能作为"
            "低置信度运行时线索；不得推断未提供的正文、日期或发布机构。\n\n"
            f"{_json(news_items)}"
        )
        social_block = (
            "DSA SOURCE CONTRACT: The records below are public investor-community search results "
            "collected through SearXNG from allowlisted Xueqiu, Zhihu, or Weibo pages. They are NOT "
            "StockTwits messages. A record with content_kind=browser_excerpt contains a bounded "
            "public-page excerpt collected by the DSA backend; content_kind=search_snippet contains "
            "only a search-engine snippet. Neither is guaranteed to be the complete page or comment "
            "thread. The model has no browser or external tools in this analyst stage: do not claim "
            "to have opened a URL or searched the web yourself, and do not infer content beyond the "
            "supplied fields. Cite source, published_date, content_fetched_at/fetched_at, and URL; "
            "lower confidence when evidence is truncated, undated, unavailable, or too sparse.\n\n"
            f"{_json(social_items)}"
        )
        return {
            # Provider-neutral sections are consumed by the compatible
            # upstream seam. Legacy keys below remain during the 0.3.1
            # transition and preserve the original default path.
            "sections": [
                {
                    "key": "domestic_news",
                    "label": "国内个股新闻与公告",
                    "source_kind": "news",
                    "provider": news_envelope.provider or "unavailable",
                    "as_of": str(news_envelope.as_of) if news_envelope.as_of else None,
                    "fetched_at": str(news_envelope.fetched_at),
                    "guidance": (
                        "区分事件事实和媒体/机构观点；search_provider 不是 publisher，"
                        "无 published_date 时降低置信度。"
                    ),
                    "records": news_items,
                },
                {
                    "key": "domestic_investor_community",
                    "label": "国内投资者社区观点（雪球、知乎、微博）",
                    "source_kind": "investor_community",
                    "provider": envelope.provider or "unavailable",
                    "as_of": str(envelope.as_of) if envelope.as_of else None,
                    "fetched_at": str(envelope.fetched_at),
                    "guidance": (
                        "只能使用实际记录；不得要求或虚构 Bullish/Bearish 标签、"
                        "upvote、comment、完整帖子或评论线程。"
                    ),
                    "records": social_items,
                },
            ],
            # Preserve the original TradingAgents multi-source sentiment
            # structure, but replace US-specific sources with explicit A-share
            # news and community evidence contracts.
            "news": news_block,
            "news_source": news_envelope.provider or "unavailable",
            "news_as_of": str(news_envelope.fetched_at),
            # TradingAgents 0.3.1 exposes only the legacy news/stocktwits/reddit
            # bundle keys. Put the DSA community block in the second slot and
            # make its true identity explicit until the pinned upstream adds a
            # provider-neutral community key.
            "stocktwits": social_block,
            "social": _json(social_items),
            "social_source": envelope.provider or "unavailable",
            "social_as_of": str(envelope.fetched_at),
            "reddit": "<unavailable: A-share Reddit source is not configured>",
        }

    @classmethod
    def _filter_items_by_date(
        cls,
        items: list[dict[str, Any]],
        *,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        start = cls._parse_date(start_date)
        end = cls._parse_date(end_date)
        selected: list[dict[str, Any]] = []
        for raw_item in items:
            item = dict(raw_item)
            published = cls._parse_date(item.get("published_date"))
            if published is None:
                item["date_filter_status"] = "undated_retained_low_confidence"
                selected.append(item)
            elif (start is None or published >= start) and (end is None or published <= end):
                item["date_filter_status"] = "within_requested_window"
                selected.append(item)
        return selected

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            digits = "".join(character for character in text if character.isdigit())[:8]
            try:
                return datetime.strptime(digits, "%Y%m%d").date()
            except ValueError:
                return None

    def fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5, benchmark: str = ""
    ) -> tuple[float | None, float | None, int | None]:
        """Resolve decision-memory returns from the same DSA daily-bar evidence."""
        return self._trace_direct_call(
            "fetch_returns",
            {
                "ticker": ticker, "trade_date": trade_date,
                "holding_days": holding_days, "benchmark": benchmark,
            },
            lambda: self._fetch_returns(ticker),
        )

    def _fetch_returns(self, ticker: str) -> tuple[float | None, float | None, int | None]:
        self._require_symbol(ticker)
        self._envelope("market_daily_bars")
        # Upstream decision memory formats alpha_return as a percentage.  A
        # mixed tuple with a raw return but alpha=None crashes that path and,
        # more importantly, pretends a benchmark-relative outcome was resolved.
        # Keep the entry pending until a canonical A-share benchmark series is
        # available for the same dates.
        return None, None, None

    def _trace_direct_call(
        self,
        name: str,
        arguments: dict[str, Any],
        operation: Callable[[], Any],
    ) -> Any:
        """Trace injected toolkit calls that are not LangGraph StructuredTools."""
        started = time.monotonic()
        operation_id = str(uuid.uuid4())
        input_payload = {"tool": name, "arguments": arguments}
        if self.trace_emit:
            self.trace_emit(event_type="tool.started", stage="tool", payload={
                "operation_id": operation_id, "input": input_payload,
            })
        try:
            result = operation()
        except Exception as exc:
            if self.trace_emit:
                self.trace_emit(event_type="tool.failed", stage="tool", payload={
                    "operation_id": operation_id,
                    "input": input_payload,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "duration_ms": round((time.monotonic() - started) * 1000),
                })
            raise
        if self.trace_emit:
            self.trace_emit(event_type="tool.completed", stage="tool", payload={
                "operation_id": operation_id,
                "input": input_payload,
                "output": {"result": result},
                "duration_ms": round((time.monotonic() - started) * 1000),
            })
        return result

    def _tool(self, name: str, description: str) -> Any:
        if name in self._tools:
            return self._tools[name]
        try:
            from langchain_core.tools import StructuredTool
        except ImportError as exc:
            raise RuntimeError("TradingAgents dependencies are not installed") from exc
        original = getattr(self, name)

        @wraps(original)
        def traced(*args, **kwargs):
            started = time.monotonic()
            operation_id = str(uuid.uuid4())
            input_payload = {"tool": name, "arguments": kwargs or args}
            if self.trace_emit:
                self.trace_emit(event_type="tool.started", stage="tool", payload={
                    "operation_id": operation_id, "input": input_payload,
                })
            try:
                result = original(*args, **kwargs)
            except Exception as exc:
                if self.trace_emit:
                    self.trace_emit(event_type="tool.failed", stage="tool", payload={
                        "operation_id": operation_id,
                        "input": input_payload,
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                        "duration_ms": round((time.monotonic() - started) * 1000),
                    })
                raise
            if self.trace_emit:
                self.trace_emit(event_type="tool.completed", stage="tool", payload={
                    "operation_id": operation_id,
                    "input": input_payload,
                    "output": {"result": result},
                    "duration_ms": round((time.monotonic() - started) * 1000),
                })
            return result

        tool = StructuredTool.from_function(func=traced, name=name, description=description)
        self._tools[name] = tool
        return tool

    @property
    def market_tools(self) -> Sequence[Any]:
        return (
            self._tool(
                "get_stock_data",
                "获取 DSA 已核验的 A 股日线 OHLCV CSV；volume 为股、amount 为人民币，复权口径见证据清单。",
            ),
            self._tool(
                "get_indicators",
                "基于同一 A 股日线确定性计算指标：macd=DIF，macds=DEA，macdh=2*(DIF-DEA)，"
                "BOLL 为 20 日中轨/上轨/下轨；只能解释工具实际返回的日期和值。",
            ),
            self._tool("get_verified_market_snapshot", "获取已核验的 A 股价格快照、价格类型和数据时点。"),
        )

    @property
    def news_tools(self) -> Sequence[Any]:
        return (
            self._tool(
                "get_news",
                "获取指定窗口内 DSA 国内个股新闻/公告；区分 search_provider、publisher、published_date 与 fetched_at。",
            ),
            self._tool(
                "get_global_news",
                "获取 A 股宏观/全市场新闻；未配置独立时点数据时明确返回不可用，绝不复用个股新闻冒充。",
            ),
            self._tool("get_macro_indicators", "Return explicit macro-data availability for this DSA run."),
            self._tool("get_prediction_markets", "Return explicit prediction-market availability for this DSA run."),
        )

    @property
    def fundamentals_tools(self) -> Sequence[Any]:
        return tuple(
            self._tool(
                name,
                "获取受公告日/可得日约束的 A 股基本面证据；报告期不等于公告日，"
                "不同报告期和业绩预告/正式财报不得混算。",
            )
            for name in ("get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement")
        )
