"""A-share instrument schema."""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel


class InstrumentContext(BaseModel):
    symbol: str
    name: str = ""
    market: Literal["cn"] = "cn"
    exchange: Literal["SH", "SZ", "BJ"]
    security_type: Literal["a_share"] = "a_share"
    currency: Literal["CNY"] = "CNY"
    trade_date: date
    description: str
    listed: Optional[bool] = None
