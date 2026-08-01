"""Run-scoped TradingAgents tools backed only by canonical DSA evidence."""

from __future__ import annotations

import json
import time
from functools import wraps
from typing import Any, Sequence

import pandas as pd

from src.trader_analysis.schemas.evidence import EvidenceEnvelope, EvidenceLedger


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, indent=2)


class DsaTradingAgentsToolkit:
    """Build matching analyst/tool-node tools for one immutable run ledger."""

    def __init__(self, ledger: EvidenceLedger, trace_emit=None) -> None:
        self.ledger = ledger
        self.symbol = ledger.symbol
        self._tools: dict[str, Any] = {}
        self.trace_emit = trace_emit

    def _require_symbol(self, ticker: str) -> None:
        normalized = str(ticker).upper().replace("SH", "").replace("SZ", "").replace("BJ", "").split(".")[0]
        if normalized != self.symbol:
            raise ValueError(f"tool symbol mismatch: expected {self.symbol}, got {ticker}")

    def _envelope(self, capability: str) -> EvidenceEnvelope:
        envelope = self.ledger.envelopes.get(capability)
        if envelope is None:
            raise ValueError(f"canonical evidence unavailable: {capability}")
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
            macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
            signal = macd.ewm(span=9, adjust=False).mean()
            values = {"macd": macd, "macds": signal, "macdh": macd - signal}[name]
        elif name == "rsi":
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = -delta.clip(upper=0).rolling(14).mean()
            values = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
        elif name in {"boll", "boll_ub", "boll_lb"}:
            middle = close.rolling(20).mean()
            deviation = close.rolling(20).std()
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
        return _json((self._envelope("news").payload or {}).get("items") or [])

    def get_global_news(self, curr_date: str, look_back_days: int = 7, limit: int = 10) -> str:
        items = list((self._envelope("news").payload or {}).get("items") or [])
        return _json(items[:limit])

    def get_insider_transactions(self, symbol: str) -> str:
        self._require_symbol(symbol)
        fundamentals = self._envelope("fundamentals").payload or {}
        return _json(fundamentals.get("institution") or {"status": "unavailable"})

    def get_macro_indicators(self, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
        return "DATA_UNAVAILABLE: no point-in-time DSA macro series is configured; do not fabricate values."

    def get_prediction_markets(self, topic: str, limit: int = 10) -> str:
        return "DATA_UNAVAILABLE: prediction markets are outside the A-share phase-1 evidence contract."

    def get_fundamentals(self, ticker: str, curr_date: str | None = None) -> str:
        self._require_symbol(ticker)
        return _json(self._envelope("fundamentals").payload or {})

    def get_balance_sheet(self, ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
        return self.get_fundamentals(ticker, curr_date)

    def get_cashflow(self, ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
        return self.get_fundamentals(ticker, curr_date)

    def get_income_statement(self, ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
        return self.get_fundamentals(ticker, curr_date)

    def prefetch_sentiment(self, ticker: str, start_date: str, end_date: str) -> dict[str, str]:
        self._require_symbol(ticker)
        payload = self._envelope("sentiment").payload or {}
        return {
            "news": _json(payload.get("news_items") or []),
            "stocktwits": "<unavailable: A-share StockTwits source is not configured>",
            "reddit": "<unavailable: A-share Reddit source is not configured>",
        }

    def fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5, benchmark: str = ""
    ) -> tuple[float | None, float | None, int | None]:
        """Resolve decision-memory returns from the same DSA daily-bar evidence."""
        self._require_symbol(ticker)
        rows = list((self._envelope("market_daily_bars").payload or {}).get("rows") or [])
        later = [row for row in rows if str(row.get("trade_date") or "") >= trade_date]
        if len(later) < 2:
            return None, None, None
        end_index = min(holding_days, len(later) - 1)
        start = float(later[0]["close"])
        end = float(later[end_index]["close"])
        if start <= 0:
            return None, None, None
        return (end / start - 1.0), None, end_index

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
            if self.trace_emit:
                self.trace_emit(event_type="tool.started", stage="tool", payload={"tool": name, "arguments": kwargs or args})
            try:
                result = original(*args, **kwargs)
            except Exception as exc:
                if self.trace_emit:
                    self.trace_emit(event_type="tool.failed", stage="tool", payload={
                        "tool": name, "error_type": type(exc).__name__, "error": str(exc),
                        "duration_ms": round((time.monotonic() - started) * 1000),
                    })
                raise
            if self.trace_emit:
                self.trace_emit(event_type="tool.completed", stage="tool", payload={
                    "tool": name, "result": result,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                })
            return result

        tool = StructuredTool.from_function(func=traced, name=name, description=description)
        self._tools[name] = tool
        return tool

    @property
    def market_tools(self) -> Sequence[Any]:
        return (
            self._tool("get_stock_data", "Get canonical DSA daily OHLCV CSV."),
            self._tool("get_indicators", "Calculate a deterministic indicator from the same DSA daily bars."),
            self._tool("get_verified_market_snapshot", "Get the verified DSA price snapshot."),
        )

    @property
    def news_tools(self) -> Sequence[Any]:
        return (
            self._tool("get_news", "Get verified company news collected by DSA."),
            self._tool("get_global_news", "Get relevant A-share context news collected by DSA."),
            self._tool("get_macro_indicators", "Return explicit macro-data availability for this DSA run."),
            self._tool("get_prediction_markets", "Return explicit prediction-market availability for this DSA run."),
        )

    @property
    def fundamentals_tools(self) -> Sequence[Any]:
        return tuple(
            self._tool(name, "Get point-in-time constrained DSA fundamental evidence.")
            for name in ("get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement")
        )
