"""Option flow: volume/premium by strike & expiration, side heuristic,
top trades.

With delayed snapshot data there is no trade-by-trade tape, so 'side' is a
heuristic on the last trade vs the current quote: at/above ask = buy,
at/below bid = sell, otherwise neutral.
"""
from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Dict, List, Optional

from .. import config
from ..models import Contract
from .gex import M, _window, bucket_strike, choose_step


def classify(last: float, bid: float, ask: float) -> str:
    if last <= 0.0:
        return "neutral"
    if ask > 0.0 and last >= ask:
        return "buy"
    if bid > 0.0 and last <= bid:
        return "sell"
    return "neutral"


def premium(c: Contract) -> float:
    return c.volume * c.last * config.CONTRACT_MULTIPLIER


def build_flow(contracts: List[Contract], spot: float, cfg: dict) -> dict:
    expiries = sorted({c.expiry for c in contracts})[:config.MAX_FLOW_EXPIRATIONS]
    keys = ["ALL"] + [e.isoformat() for e in expiries]
    step = choose_step(spot, cfg["window_pct"], cfg["steps"], config.MAX_HEATMAP_ROWS)
    lo, hi = _window(spot, cfg["window_pct"])

    def rows_for(expiry: Optional[datetime.date]) -> dict:
        acc: Dict[float, List[float]] = {}
        tot = {"call_vol": 0, "put_vol": 0, "call_prem": 0.0, "put_prem": 0.0}
        for c in contracts:
            if expiry is not None and c.expiry != expiry:
                continue
            p = premium(c) if c.volume > 0 else 0.0
            if c.cp == "C":
                tot["call_vol"] += c.volume
                tot["call_prem"] += p
            else:
                tot["put_vol"] += c.volume
                tot["put_prem"] += p
            if not (lo <= c.strike <= hi):
                continue
            # A zero ask is an absent/unusable quote. A zero bid can still be
            # a valid penny-option quote, so retain it when the ask is quoted.
            has_spread = c.ask > 0.0 and c.ask >= c.bid
            if c.volume <= 0 and c.oi <= 0 and not has_spread:
                continue
            b = bucket_strike(c.strike, step)
            # strike, call/put volume, call/put premium, call/put OI,
            # call/put spread sums and quote counts
            row = acc.setdefault(b, [b, 0, 0, 0.0, 0.0, 0, 0, 0.0, 0.0, 0, 0])
            if c.cp == "C":
                row[1] += c.volume
                row[3] += p
                row[5] += c.oi
                if has_spread:
                    row[7] += c.ask - c.bid
                    row[9] += 1
            else:
                row[2] += c.volume
                row[4] += p
                row[6] += c.oi
                if has_spread:
                    row[8] += c.ask - c.bid
                    row[10] += 1
        rows = []
        for b in sorted(acc, reverse=True):
            r = acc[b]
            rows.append([
                r[0], r[1], r[2], round(r[3] / M, 2), round(r[4] / M, 2),
                r[5], r[6],
                round(r[7] / r[9], 4) if r[9] else None,
                round(r[8] / r[10], 4) if r[10] else None,
            ])
        return {
            "rows": rows,
            "call_vol": tot["call_vol"], "put_vol": tot["put_vol"],
            "call_prem_m": round(tot["call_prem"] / M, 1),
            "put_prem_m": round(tot["put_prem"] / M, 1),
        }

    by_expiry = {"ALL": rows_for(None)}
    for e in expiries:
        by_expiry[e.isoformat()] = rows_for(e)

    # Top single contracts by premium with buy/sell classification.
    traded = [c for c in contracts if c.volume > 0 and c.last > 0]
    traded.sort(key=premium, reverse=True)
    top_trades = []
    side_prem = defaultdict(float)
    for c in traded:
        side_prem[classify(c.last, c.bid, c.ask)] += premium(c)
    for c in traded[:config.TOP_TRADES]:
        top_trades.append({
            "strike": c.strike,
            "cp": c.cp,
            "expiry": c.expiry.isoformat(),
            "volume": c.volume,
            "last": c.last,
            "premium_m": round(premium(c) / M, 2),
            "side": classify(c.last, c.bid, c.ask),
        })

    return {
        "expiries": keys,
        "step": step,
        "by_expiry": by_expiry,
        "top_trades": top_trades,
        "totals": {
            "call_vol": by_expiry["ALL"]["call_vol"],
            "put_vol": by_expiry["ALL"]["put_vol"],
            "call_prem_m": by_expiry["ALL"]["call_prem_m"],
            "put_prem_m": by_expiry["ALL"]["put_prem_m"],
            "prem_buy_m": round(side_prem["buy"] / M, 1),
            "prem_sell_m": round(side_prem["sell"] / M, 1),
            "prem_neutral_m": round(side_prem["neutral"] / M, 1),
        },
    }
