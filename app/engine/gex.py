"""GEX/DEX math: totals, strike profiles, walls, gamma flip, heatmap,
strike map, 0DTE view.

Conventions (standard dealer-positioning model, same as the reference site):
  GEX(contract) = +/- gamma * OI * 100 * spot^2 * 0.01   (call +, put -)
  DEX(contract) = delta * OI * 100 * spot                (puts negative via delta)
GEX is dollars of dealer-hedge notional per 1% spot move. Values are
serialized in $ millions (1dp) to keep payloads small; totals in $ billions.
"""
from __future__ import annotations

import datetime
import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .. import config
from ..models import Contract

M = 1e6
BN = 1e9


def contract_gex(c: Contract, spot: float) -> float:
    sign = 1.0 if c.cp == "C" else -1.0
    return sign * c.gamma * c.oi * config.CONTRACT_MULTIPLIER * spot * spot * 0.01


def contract_dex(c: Contract, spot: float) -> float:
    return c.delta * c.oi * config.CONTRACT_MULTIPLIER * spot


def totals(contracts: List[Contract], spot: float) -> dict:
    """Whole-chain aggregates (no strike window)."""
    t = {"net_gex": 0.0, "call_gex": 0.0, "put_gex": 0.0,
         "net_dex": 0.0, "call_dex": 0.0, "put_dex": 0.0,
         "call_vol": 0, "put_vol": 0, "call_oi": 0, "put_oi": 0}
    for c in contracts:
        g = contract_gex(c, spot)
        d = contract_dex(c, spot)
        t["net_gex"] += g
        t["net_dex"] += d
        if c.cp == "C":
            t["call_gex"] += g
            t["call_dex"] += d
            t["call_vol"] += c.volume
            t["call_oi"] += c.oi
        else:
            t["put_gex"] += g
            t["put_dex"] += d
            t["put_vol"] += c.volume
            t["put_oi"] += c.oi
    return t


def choose_step(spot: float, window_pct: float, steps: List[float],
                max_rows: int) -> float:
    """Smallest bucket step that keeps the strike window under max_rows."""
    span = 2.0 * spot * window_pct
    for s in steps:
        if span / s <= max_rows:
            return s
    return steps[-1]


def bucket_strike(strike: float, step: float) -> float:
    b = round(strike / step) * step
    return round(b, 2)


def strike_profile(contracts: List[Contract], spot: float,
                   expiry: Optional[datetime.date] = None) -> List[dict]:
    """Unbucketed net GEX per true strike, ascending. Used for walls/flip so
    levels land on real strikes, not buckets."""
    acc: Dict[float, dict] = {}
    for c in contracts:
        if expiry is not None and c.expiry != expiry:
            continue
        g = contract_gex(c, spot)
        if g == 0.0:
            continue
        row = acc.setdefault(c.strike, {"strike": c.strike, "call_gex": 0.0,
                                        "put_gex": 0.0, "net_gex": 0.0})
        row["net_gex"] += g
        if c.cp == "C":
            row["call_gex"] += g
        else:
            row["put_gex"] += g
    return [acc[k] for k in sorted(acc)]


def find_walls(profile: List[dict]) -> Tuple[Optional[float], Optional[float]]:
    """(call_wall, put_wall): strikes of max positive / min negative net GEX."""
    call_wall = put_wall = None
    hi = lo = 0.0
    for row in profile:
        if row["net_gex"] > hi:
            hi, call_wall = row["net_gex"], row["strike"]
        if row["net_gex"] < lo:
            lo, put_wall = row["net_gex"], row["strike"]
    return call_wall, put_wall


def _bs_gamma(spot: float, strike: float, iv: float, years: float) -> float:
    """Black-Scholes unit gamma using zero rates.

    Rates and dividends have a small effect on the structural flip compared
    with IV and time. Zero rates keep the estimate reproducible without
    introducing another delayed external input.
    """
    if spot <= 0 or strike <= 0 or iv <= 0 or years <= 0:
        return 0.0
    vol_time = iv * math.sqrt(years)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * years) / vol_time
    density = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return density / (spot * vol_time)


def _years_to_expiry(expiry: datetime.date, as_of: datetime.datetime) -> float:
    """Approximate time remaining, retaining a half session for 0DTE."""
    days = (expiry - as_of.date()).days
    return max(days + 0.5, 0.5) / 365.0


def net_gex_at_spot(contracts: List[Contract], candidate_spot: float,
                    as_of: datetime.datetime,
                    expiry: Optional[datetime.date] = None) -> float:
    """Reprice gamma and aggregate assumed dealer GEX at a candidate spot."""
    total = 0.0
    for c in contracts:
        if expiry is not None and c.expiry != expiry:
            continue
        if c.oi <= 0 or c.iv <= 0:
            continue
        gamma = _bs_gamma(
            candidate_spot, c.strike, c.iv,
            _years_to_expiry(c.expiry, as_of),
        )
        sign = 1.0 if c.cp == "C" else -1.0
        total += (sign * gamma * c.oi * config.CONTRACT_MULTIPLIER
                  * candidate_spot * candidate_spot * 0.01)
    return total


def find_gamma_flip(contracts: List[Contract], spot: float,
                    as_of: datetime.datetime,
                    expiry: Optional[datetime.date] = None) -> Optional[float]:
    """Find the repriced aggregate-GEX zero nearest spot.

    The search spans +/-20% around spot. Each bracketed crossing is refined by
    bisection, and the crossing nearest current spot is returned.
    """
    eligible = [c for c in contracts
                if (expiry is None or c.expiry == expiry) and c.oi > 0 and c.iv > 0]
    if not eligible or spot <= 0:
        return None
    lo, hi = spot * 0.8, spot * 1.2
    steps = 160
    points = [lo + (hi - lo) * i / steps for i in range(steps + 1)]
    values = [net_gex_at_spot(eligible, value, as_of) for value in points]
    crossings = []
    for left, right, f_left, f_right in zip(points, points[1:], values, values[1:]):
        if f_left == 0.0:
            crossings.append(left)
            continue
        if f_left * f_right > 0.0:
            continue
        for _ in range(40):
            mid = (left + right) / 2.0
            f_mid = net_gex_at_spot(eligible, mid, as_of)
            if f_left * f_mid <= 0.0:
                right, f_right = mid, f_mid
            else:
                left, f_left = mid, f_mid
        crossings.append((left + right) / 2.0)
    if not crossings:
        return None
    return min(crossings, key=lambda value: abs(value - spot))


def _window(spot: float, window_pct: float) -> Tuple[float, float]:
    return spot * (1.0 - window_pct), spot * (1.0 + window_pct)


def _grid(spot: float, step: float, lo: float, hi: float) -> List[float]:
    """Bucket centers (multiples of step) covering [lo, hi], descending."""
    first = bucket_strike(lo, step)
    if first < lo - step / 2.0:
        first += step
    out = []
    k = first
    while k <= hi + step / 2.0:
        out.append(round(k, 2))
        k += step
    return list(reversed(out))


def _expiries(contracts: List[Contract], limit: int) -> List[datetime.date]:
    return sorted({c.expiry for c in contracts})[:limit]


def build_heatmap(contracts: List[Contract], spot: float, cfg: dict) -> dict:
    """Strikes (rows, desc) x expirations (cols) net-GEX matrix, $M values.
    Off-grid strikes fold into the nearest bucket so window totals are
    conserved."""
    expiries = _expiries(contracts, config.MAX_EXPIRATIONS)
    exp_idx = {e: i for i, e in enumerate(expiries)}
    step = choose_step(spot, cfg["window_pct"], cfg["steps"], config.MAX_HEATMAP_ROWS)
    lo, hi = _window(spot, cfg["window_pct"])
    strikes = _grid(spot, step, lo, hi)          # descending
    row_idx = {s: i for i, s in enumerate(strikes)}

    cells: Dict[Tuple[int, int], float] = defaultdict(float)
    for c in contracts:
        if c.expiry not in exp_idx or not (lo <= c.strike <= hi):
            continue
        g = contract_gex(c, spot)
        if g == 0.0:
            continue
        b = bucket_strike(c.strike, step)
        if b in row_idx:
            cells[(exp_idx[c.expiry], row_idx[b])] += g

    out_cells = []
    max_abs = 0.0
    for (x, y), v in cells.items():
        vm = round(v / M, 1)
        if vm != 0.0:
            out_cells.append([x, y, vm])
            max_abs = max(max_abs, abs(vm))

    spot_row = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot)) if strikes else None
    return {
        "strikes": strikes,
        "expiries": [e.isoformat() for e in expiries],
        "step": step,
        "spot_row": spot_row,
        "max_abs": max_abs,
        "cells": out_cells,
    }


def _bucketed_rows(contracts: List[Contract], spot: float, step: float,
                   lo: float, hi: float,
                   expiry: Optional[datetime.date] = None) -> List[list]:
    """[[strike desc, call_gex_m, put_gex_m, net_gex_m], ...] within window."""
    acc: Dict[float, List[float]] = {}
    for c in contracts:
        if expiry is not None and c.expiry != expiry:
            continue
        if not (lo <= c.strike <= hi):
            continue
        g = contract_gex(c, spot)
        if g == 0.0:
            continue
        b = bucket_strike(c.strike, step)
        row = acc.setdefault(b, [b, 0.0, 0.0, 0.0])
        if c.cp == "C":
            row[1] += g
        else:
            row[2] += g
        row[3] += g
    rows = []
    for b in sorted(acc, reverse=True):
        r = acc[b]
        rows.append([r[0], round(r[1] / M, 1), round(r[2] / M, 1), round(r[3] / M, 1)])
    return rows


def build_strikemap(contracts: List[Contract], spot: float, cfg: dict,
                    as_of: Optional[datetime.datetime] = None) -> dict:
    """Per-expiration strike ladders + walls/flip, plus summary tables."""
    expiries = _expiries(contracts, config.MAX_STRIKEMAP_EXPIRATIONS)
    step = choose_step(spot, cfg["window_pct"], cfg["steps"], config.MAX_HEATMAP_ROWS)
    lo, hi = _window(spot, cfg["window_pct"])

    as_of = as_of or datetime.datetime.now(tz=datetime.timezone.utc)
    by_expiry: Dict[str, dict] = {}
    keys = ["ALL"] + [e.isoformat() for e in expiries]
    for key in keys:
        exp = None if key == "ALL" else datetime.date.fromisoformat(key)
        profile = strike_profile(contracts, spot, expiry=exp)
        call_wall, put_wall = find_walls(profile)
        flip = find_gamma_flip(contracts, spot, as_of, expiry=exp)
        by_expiry[key] = {
            "rows": _bucketed_rows(contracts, spot, step, lo, hi, expiry=exp),
            "call_wall": call_wall,
            "put_wall": put_wall,
            "flip": round(flip, 2) if flip is not None else None,
        }

    all_profile = strike_profile(contracts, spot)
    pos = sorted((r for r in all_profile if r["net_gex"] > 0),
                 key=lambda r: r["net_gex"], reverse=True)[:config.TOP_STRIKES]
    neg = sorted((r for r in all_profile if r["net_gex"] < 0),
                 key=lambda r: r["net_gex"])[:config.TOP_STRIKES]

    gex_by_expiry = []
    per_exp: Dict[datetime.date, float] = defaultdict(float)
    for c in contracts:
        if c.expiry in set(expiries):
            per_exp[c.expiry] += contract_gex(c, spot)
    for e in expiries:
        gex_by_expiry.append([e.isoformat(), round(per_exp[e] / M, 1)])

    return {
        "expiries": keys,
        "step": step,
        "by_expiry": by_expiry,
        "top_pos": [[r["strike"], round(r["net_gex"] / M, 1)] for r in pos],
        "top_neg": [[r["strike"], round(r["net_gex"] / M, 1)] for r in neg],
        "gex_by_expiry": gex_by_expiry,
    }


def build_expiry_levels(contracts: List[Contract], spot: float,
                        as_of: Optional[datetime.datetime] = None) -> Dict[str, dict]:
    """Wall and flip levels for every expiration in the chain."""
    as_of = as_of or datetime.datetime.now(tz=datetime.timezone.utc)
    levels = {}
    for expiry in sorted({c.expiry for c in contracts}):
        profile = strike_profile(contracts, spot, expiry=expiry)
        call_wall, put_wall = find_walls(profile)
        flip = find_gamma_flip(contracts, spot, as_of, expiry=expiry)
        levels[expiry.isoformat()] = {
            "call_wall": call_wall,
            "flip": round(flip, 2) if flip is not None else None,
            "put_wall": put_wall,
        }
    return levels


def build_zero_dte(contracts: List[Contract], spot: float, cfg: dict,
                   today: datetime.date,
                   as_of: Optional[datetime.datetime] = None) -> dict:
    """Same-day expiration roadmap; friendly empty state when none trades."""
    todays = [c for c in contracts if c.expiry == today]
    if not todays:
        future = sorted({c.expiry for c in contracts})
        return {"available": False,
                "next_expiry": future[0].isoformat() if future else None}

    step = choose_step(spot, config.ZERO_DTE_WINDOW_PCT, cfg["steps"],
                       config.ZERO_DTE_MAX_ROWS)
    lo, hi = _window(spot, config.ZERO_DTE_WINDOW_PCT)
    profile = strike_profile(todays, spot)
    call_wall, put_wall = find_walls(profile)
    as_of = as_of or datetime.datetime.combine(
        today, datetime.time(12, 0), tzinfo=datetime.timezone.utc)
    flip = find_gamma_flip(todays, spot, as_of, expiry=today)

    dte_vol = sum(c.volume for c in todays)
    total_vol = sum(c.volume for c in contracts)
    dte_gex = sum(contract_gex(c, spot) for c in todays)

    return {
        "available": True,
        "expiry": today.isoformat(),
        "step": step,
        "rows": _bucketed_rows(todays, spot, step, lo, hi),
        "call_wall": call_wall,
        "put_wall": put_wall,
        "flip": round(flip, 2) if flip is not None else None,
        "stats": {
            "dte_volume": dte_vol,
            "dte_share_pct": round(100.0 * dte_vol / total_vol, 1) if total_vol else 0.0,
            "dte_net_gex_m": round(dte_gex / M, 1),
        },
    }
