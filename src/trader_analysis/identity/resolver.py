"""Strict first-phase A-share identity resolver."""

from __future__ import annotations

import re
from datetime import date

from src.trader_analysis.schemas.instrument import InstrumentContext


_SYMBOL_RE = re.compile(r"^(?:(SH|SZ|BJ))?(\d{6})(?:\.(SH|SZ|BJ))?$", re.IGNORECASE)


class UnsupportedInstrumentError(ValueError):
    pass


def normalize_a_share_symbol(raw_symbol: str) -> tuple[str, str]:
    value = (raw_symbol or "").strip().upper()
    match = _SYMBOL_RE.match(value)
    if not match:
        raise UnsupportedInstrumentError("第一阶段只支持沪深北普通 A 股六位代码")

    prefix, digits, suffix = match.groups()
    exchange = prefix or suffix
    inferred = _infer_exchange(digits)
    if exchange and exchange != inferred:
        raise UnsupportedInstrumentError("股票代码与交易所前后缀不一致")
    return digits, inferred


def _infer_exchange(symbol: str) -> str:
    if symbol.startswith(("60", "68", "90")):
        return "SH"
    if symbol.startswith(("00", "001", "002", "003", "30", "20")):
        return "SZ"
    if symbol.startswith(("43", "83", "87", "88", "92")):
        return "BJ"
    raise UnsupportedInstrumentError("该代码不在第一阶段普通 A 股支持范围内")


def resolve_instrument(raw_symbol: str, trade_date: date, name: str = "") -> InstrumentContext:
    symbol, exchange = normalize_a_share_symbol(raw_symbol)
    exchange_name = {"SH": "上海证券交易所", "SZ": "深圳证券交易所", "BJ": "北京证券交易所"}[exchange]
    display_name = name.strip() or symbol
    description = (
        f"当前标的是{display_name}（{symbol}），{exchange_name}普通 A 股，"
        f"报价币种人民币（CNY），分析日期 {trade_date.isoformat()}。"
        f"所有工具调用和报告必须保持代码 {symbol}，不得替换成其他证券。"
    )
    return InstrumentContext(
        symbol=symbol,
        name=display_name,
        exchange=exchange,  # type: ignore[arg-type]
        trade_date=trade_date,
        description=description,
    )
