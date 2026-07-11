"""Data models shared across provider and engines."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import List


@dataclass
class Contract:
    root: str                 # SPX | SPXW
    expiry: datetime.date
    cp: str                   # "C" | "P"
    strike: float
    bid: float
    ask: float
    last: float
    iv: float                 # decimal (0.24 = 24%)
    oi: int
    volume: int
    delta: float
    gamma: float


@dataclass
class ChainData:
    symbol: str
    spot: float
    change_pct: float
    iv30: float               # percent points (16.1)
    iv30_change_pct: float
    data_ts: datetime.datetime        # tz-aware (ET source)
    last_trade_time: datetime.datetime  # tz-aware (ET source)
    contracts: List[Contract] = field(default_factory=list)


@dataclass
class VixData:
    level: float
    change_pct: float
    ts: datetime.datetime
