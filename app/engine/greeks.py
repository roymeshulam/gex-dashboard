"""Black-Scholes option-price sensitivity curves for the Greeks view."""
from __future__ import annotations

import datetime
import math
from typing import Iterable

from ..models import Contract

RISK_FREE_RATE = 0.043
DIVIDEND_YIELD = 0.0


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _round_to_25(value: float) -> float:
    """Round an index level to the nearest 25-point increment."""
    return math.floor(value / 25.0 + 0.5) * 25.0


def option_price(spot: float, strike: float, years: float, iv: float,
                 cp: str, rate: float = RISK_FREE_RATE,
                 dividend_yield: float = DIVIDEND_YIELD) -> float:
    """Return a European Black-Scholes price, including the expiry boundary."""
    intrinsic = max(spot - strike, 0.0) if cp == "C" else max(strike - spot, 0.0)
    if years <= 0.0 or iv <= 0.0 or spot <= 0.0 or strike <= 0.0:
        return intrinsic
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) +
          (rate - dividend_yield + 0.5 * iv * iv) * years) / (iv * root_t)
    d2 = d1 - iv * root_t
    if cp == "C":
        return (spot * math.exp(-dividend_yield * years) * _normal_cdf(d1) -
                strike * math.exp(-rate * years) * _normal_cdf(d2))
    return (strike * math.exp(-rate * years) * _normal_cdf(-d2) -
            spot * math.exp(-dividend_yield * years) * _normal_cdf(-d1))


def option_metrics(spot: float, strike: float, years: float, iv: float,
                   cp: str, rate: float = RISK_FREE_RATE,
                   dividend_yield: float = DIVIDEND_YIELD) -> dict:
    """Return price and standard Black-Scholes Greeks for one option."""
    price = option_price(spot, strike, years, iv, cp, rate, dividend_yield)
    if years <= 0.0 or iv <= 0.0 or spot <= 0.0 or strike <= 0.0:
        if cp == "C":
            delta = 1.0 if spot > strike else (0.5 if spot == strike else 0.0)
        else:
            delta = -1.0 if spot < strike else (-0.5 if spot == strike else 0.0)
        return {"price": price, "delta": delta, "gamma": 0.0,
                "theta": 0.0, "vega": 0.0}

    root_t = math.sqrt(years)
    discount_q = math.exp(-dividend_yield * years)
    discount_r = math.exp(-rate * years)
    d1 = (math.log(spot / strike) +
          (rate - dividend_yield + 0.5 * iv * iv) * years) / (iv * root_t)
    d2 = d1 - iv * root_t
    pdf = _normal_pdf(d1)
    gamma = discount_q * pdf / (spot * iv * root_t)
    vega = spot * discount_q * pdf * root_t / 100.0
    common_theta = -(spot * discount_q * pdf * iv) / (2.0 * root_t)
    if cp == "C":
        delta = discount_q * _normal_cdf(d1)
        theta = (common_theta - rate * strike * discount_r * _normal_cdf(d2) +
                 dividend_yield * spot * discount_q * _normal_cdf(d1)) / 365.0
    else:
        delta = discount_q * (_normal_cdf(d1) - 1.0)
        theta = (common_theta + rate * strike * discount_r * _normal_cdf(-d2) -
                 dividend_yield * spot * discount_q * _normal_cdf(-d1)) / 365.0
    return {"price": price, "delta": delta, "gamma": gamma,
            "theta": theta, "vega": vega}


def build_surface(contracts: Iterable[Contract], spot: float,
                  today: datetime.date) -> dict:
    """Retain only quoted IVs needed for interactive server-side pricing."""
    rows = {}
    for contract in contracts:
        if contract.iv <= 0.0 or contract.expiry < today:
            continue
        key = (contract.expiry.isoformat(), contract.strike, contract.cp)
        current = rows.get(key)
        # Prefer the tighter, live quote if duplicate roots describe a contract.
        spread = contract.ask - contract.bid if contract.ask >= contract.bid else math.inf
        if current is None or spread < current[1]:
            rows[key] = (contract.iv, spread)

    expiries = sorted({key[0] for key in rows})
    by_expiry = {}
    for expiry in expiries:
        strikes = sorted({key[1] for key in rows if key[0] == expiry})
        by_expiry[expiry] = {
            "dte": max((datetime.date.fromisoformat(expiry) - today).days, 0),
            "rows": [
                [strike,
                 rows.get((expiry, strike, "C"), (None,))[0],
                 rows.get((expiry, strike, "P"), (None,))[0]]
                for strike in strikes
            ],
        }
    return {"spot": spot, "expiries": expiries, "by_expiry": by_expiry}


def _selected_row(surface: dict, expiry: str, strike: float, cp: str) -> tuple[float, float]:
    rows = surface["by_expiry"][expiry]["rows"]
    iv_index = 1 if cp == "C" else 2
    usable = [row for row in rows if row[iv_index] is not None]
    if not usable:
        raise ValueError("no implied volatility available for this option type")
    row = min(usable, key=lambda item: (abs(item[0] - strike), item[0]))
    return row[0], row[iv_index]


def calculate_curves(surface: dict, expiry: str, strike: float, cp: str) -> dict:
    cp = cp.upper()
    if cp not in {"C", "P"}:
        raise ValueError("cp must be C or P")
    if expiry not in surface["by_expiry"]:
        raise ValueError("unknown expiry")

    strike, iv = _selected_row(surface, expiry, strike, cp)
    spot = surface["spot"]
    dte = surface["by_expiry"][expiry]["dte"]
    years = max(dte, 0.25) / 365.0
    expected_move = spot * iv * math.sqrt(years)
    spot_lower = _round_to_25(spot - expected_move)
    spot_upper = _round_to_25(spot + expected_move)

    metrics = ("price", "delta", "gamma", "theta", "vega")
    curves = {metric: {"spot": [], "volatility": [], "time": []} for metric in metrics}
    for index in range(61):
        x = spot_lower + (spot_upper - spot_lower) * index / 60.0
        values = option_metrics(x, strike, years, iv, cp)
        for metric in metrics:
            curves[metric]["spot"].append([round(x, 2), round(values[metric], 6)])

    # Show a symmetric relative shock around the selected contract's IV:
    # 50% below through 50% above (for example, 20% IV -> 10%-30%).
    low_iv = max(0.01, iv * 0.5)
    high_iv = iv * 1.5
    for index in range(61):
        x = low_iv + (high_iv - low_iv) * index / 60.0
        values = option_metrics(spot, strike, years, x, cp)
        for metric in metrics:
            curves[metric]["volatility"].append(
                [round(x * 100.0, 2), round(values[metric], 6)])

    for cycle_dte in range(dte, -1, -1):
        values = option_metrics(spot, strike, cycle_dte / 365.0, iv, cp)
        for metric in metrics:
            curves[metric]["time"].append(
                [cycle_dte, round(values[metric], 6),
                 round(iv * 100.0, 2)])

    return {
        "expiry": expiry, "strike": strike, "cp": cp, "spot": round(spot, 2),
        "dte": dte, "iv_pct": round(iv * 100.0, 2),
        "expected_move": round(expected_move, 2),
        "spot_lower": spot_lower, "spot_upper": spot_upper,
        "rate_pct": round(RISK_FREE_RATE * 100.0, 2),
        "curves": curves,
        # Retain the original price fields for API compatibility.
        "spot_curve": curves["price"]["spot"],
        "volatility_curve": curves["price"]["volatility"],
        "time_curve": curves["price"]["time"],
    }
