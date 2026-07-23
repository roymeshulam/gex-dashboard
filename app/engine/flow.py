"""Option flow: volume/premium by strike & expiration, side heuristic,
top trades.

With delayed snapshot data there is no trade-by-trade tape, so 'side' is a
heuristic on the last trade vs the current quote: at/above ask = buy,
at/below bid = sell, otherwise neutral.
"""
from __future__ import annotations

import datetime
import math
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


def _round_to_25(value: float) -> float:
    """Round a positive index level to the nearest 25-point increment."""
    return math.floor(value / 25.0 + 0.5) * 25.0


def _expected_move(contracts: List[Contract], spot: float,
                   expiry: Optional[datetime.date],
                   today: datetime.date) -> Optional[dict]:
    """Return ATM-straddle expected-move bounds for one expiration."""
    if expiry is None:
        return None

    def usable(c: Contract) -> bool:
        return c.expiry == expiry and c.bid >= 0.0 and c.ask > 0.0 and c.ask >= c.bid

    calls = [c for c in contracts if c.cp == "C" and usable(c)]
    puts = [c for c in contracts if c.cp == "P" and usable(c)]
    if not calls or not puts:
        return None

    call = min(calls, key=lambda c: (abs(c.strike - spot), c.strike))
    put = min(puts, key=lambda c: (abs(c.strike - spot), c.strike))
    call_mid = (call.bid + call.ask) / 2.0
    put_mid = (put.bid + put.ask) / 2.0
    move = call_mid + put_mid
    atm_iv = ((call.iv + put.iv) / 2.0
              if call.iv > 0.0 and put.iv > 0.0 else None)
    dte = max((expiry - today).days, 0)
    standard_deviation = (spot * atm_iv * math.sqrt(dte / 365.0)
                          if atm_iv is not None else None)
    return {
        "lower": _round_to_25(spot - move),
        "upper": _round_to_25(spot + move),
        "straddle": round(move, 2),
        "call_strike": call.strike,
        "put_strike": put.strike,
        "atm_iv_pct": round(atm_iv * 100.0, 2) if atm_iv is not None else None,
        "standard_deviation": round(standard_deviation, 2)
                              if standard_deviation is not None else None,
        "sd_lower": _round_to_25(spot - standard_deviation)
                    if standard_deviation is not None else None,
        "sd_upper": _round_to_25(spot + standard_deviation)
                    if standard_deviation is not None else None,
    }


def build_expected_ranges(contracts: List[Contract], spot: float,
                          levels: dict, today: datetime.date) -> dict:
    """Strike-level expected ranges and GEX walls through the UI horizon."""
    rows = []
    expiries = sorted({
        c.expiry for c in contracts
        if 0 <= (c.expiry - today).days <= config.MAX_EXPIRY_DTE
    })
    for expiry in expiries:
        key = expiry.isoformat()
        expected = _expected_move(contracts, spot, expiry, today)
        walls = levels.get(key, {})
        rows.append({
            "expiry": key,
            "dte": max((expiry - today).days, 0),
            "call_1sd": expected["sd_upper"] if expected else None,
            "call_expected_move": expected["upper"] if expected else None,
            "call_wall": walls.get("call_wall"),
            "put_wall": walls.get("put_wall"),
            "put_expected_move": expected["lower"] if expected else None,
            "put_1sd": expected["sd_lower"] if expected else None,
        })
    return {"rows": rows}


def build_flow(contracts: List[Contract], spot: float, cfg: dict,
               today: Optional[datetime.date] = None) -> dict:
    today = today or datetime.date.today()
    expiries = sorted({
        c.expiry for c in contracts
        if 0 <= (c.expiry - today).days <= config.MAX_EXPIRY_DTE
    })
    keys = [e.isoformat() for e in expiries]
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
            "expected_move": _expected_move(contracts, spot, expiry, today),
            "call_vol": tot["call_vol"], "put_vol": tot["put_vol"],
            "call_prem_m": round(tot["call_prem"] / M, 1),
            "put_prem_m": round(tot["put_prem"] / M, 1),
        }

    by_expiry = {"ALL": rows_for(None)}
    for e in expiries:
        by_expiry[e.isoformat()] = rows_for(e)

    term_structure = []
    expected_move_term_structure = []
    for e in expiries:
        expected = by_expiry[e.isoformat()]["expected_move"]
        if expected:
            expected_move_term_structure.append({
                "expiry": e.isoformat(),
                "dte": max((e - today).days, 0),
                "lower": expected["lower"],
                "upper": expected["upper"],
            })
        if expected and expected["atm_iv_pct"] is not None:
            term_structure.append({
                "expiry": e.isoformat(),
                "dte": max((e - today).days, 0),
                "atm_iv_pct": expected["atm_iv_pct"],
            })

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
        "term_structure": term_structure,
        "expected_move_term_structure": expected_move_term_structure,
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
