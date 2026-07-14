"""Directional-pressure and volatility-regime market-state estimates."""
from __future__ import annotations

import datetime
from typing import List, Optional

from .. import config
from ..models import ChainData, Contract, VixData
from .gex import BN


COMPONENT_DESCRIPTIONS = {
    "gamma_regime": (
        "Measures SPX's percentage distance from the repriced gamma flip. "
        "Positive net GEX is associated with more stable, mean-reverting "
        "conditions; negative net GEX can amplify moves."
    ),
    "pcr_volume": (
        "Total put volume divided by total call volume across the chain. "
        "Values above 1 mean more puts traded; values below 1 mean more calls. "
        "Volume is unsigned, so it does not identify buying versus selling."
    ),
    "dex_tilt": (
        "Net option delta exposure divided by total absolute call and put "
        "delta exposure. Positive values indicate call-dominated directional "
        "exposure; negative values indicate put-dominated exposure."
    ),
    "vix_change": (
        "The VIX percentage change from the previous close. Rising VIX signals "
        "increasing near-term expected volatility; falling VIX signals easing "
        "volatility expectations."
    ),
    "pcr_oi": (
        "Total put open interest divided by total call open interest. Higher "
        "values indicate more outstanding put positioning. Open interest is "
        "updated daily and does not reveal who owns each side."
    ),
    "iv_skew": (
        "Approximately 30-day 25-delta put implied volatility minus comparable "
        "call implied volatility, in volatility points. Higher skew indicates "
        "richer downside protection and greater concern about downside risk."
    ),
    "price_momentum": (
        "The current SPX percentage change from its previous close. Positive "
        "values show bullish pressure today and negative values show bearish "
        "pressure; this describes the current session rather than forecasting it."
    ),
    "iv30_change": (
        "The percentage change in 30-day SPX implied volatility from the "
        "previous close. Rising IV30 suggests expanding expected movement; "
        "falling IV30 suggests contracting expected movement."
    ),
}


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def iv_skew_25d(contracts: List[Contract], today: datetime.date) -> Optional[float]:
    """25-delta put IV minus 25-delta call IV (vol points) at the expiry
    closest to 30 DTE. Positive = puts richer (fear)."""
    expiries = sorted({c.expiry for c in contracts})
    if not expiries:
        return None
    target = min(expiries, key=lambda e: abs((e - today).days - config.SKEW_TARGET_DTE))
    puts = [c for c in contracts
            if c.expiry == target and c.cp == "P" and c.iv > 0 and c.oi > 0]
    calls = [c for c in contracts
             if c.expiry == target and c.cp == "C" and c.iv > 0 and c.oi > 0]
    if not puts or not calls:
        return None
    p = min(puts, key=lambda c: abs(c.delta + config.SKEW_TARGET_DELTA))
    c_ = min(calls, key=lambda c: abs(c.delta - config.SKEW_TARGET_DELTA))
    return (p.iv - c_.iv) * 100.0  # option iv is decimal -> vol points


def max_pain(contracts: List[Contract], expiry: datetime.date) -> Optional[float]:
    """Strike minimizing total intrinsic payout to option holders at expiry."""
    chain = [c for c in contracts if c.expiry == expiry and c.oi > 0]
    if not chain:
        return None
    strikes = sorted({c.strike for c in chain})
    best_strike, best_pay = None, None
    for s in strikes:
        pay = 0.0
        for c in chain:
            if c.cp == "C" and s > c.strike:
                pay += c.oi * (s - c.strike)
            elif c.cp == "P" and s < c.strike:
                pay += c.oi * (c.strike - s)
        if best_pay is None or pay < best_pay:
            best_strike, best_pay = s, pay
    return best_strike


def compute_sentiment(chain: ChainData, gex_totals: dict, flip: Optional[float],
                      vix: Optional[VixData], today: datetime.date,
                      zero_dte_share: float) -> dict:
    spot = chain.spot
    direction_components = []
    volatility_components = []

    def add(group: str, name: str, label: str, raw, score: Optional[float]):
        if raw is None or score is None:
            return
        weights = (config.DIRECTION_WEIGHTS if group == "direction"
                   else config.VOLATILITY_WEIGHTS)
        target = direction_components if group == "direction" else volatility_components
        target.append({"name": name, "label": label, "group": group,
                       "description": COMPONENT_DESCRIPTIONS[name],
                       "raw": raw, "score": round(score, 1),
                       "weight": weights[name]})

    # 1. Gamma regime: how far spot sits above/below the flip, in % of spot.
    if flip is not None and spot:
        dist = (spot - flip) / spot * 100.0
        # Positive-GEX structure is stabilizing; negative GEX is destabilizing.
        regime_sign = (-1.0 if gex_totals["net_gex"] > 0 else
                       1.0 if gex_totals["net_gex"] < 0 else 0.0)
        add("volatility", "gamma_regime", "Distance to gamma flip (%)",
            round(dist, 2), regime_sign * _clamp(abs(dist) / 1.5) * 100.0)

    # 2. Put/Call volume ratio. 1.0 neutral; lower = call-heavy = bullish.
    if gex_totals["call_vol"] > 0:
        pcr_v = gex_totals["put_vol"] / gex_totals["call_vol"]
        add("direction", "pcr_volume", "Put/Call ratio (volume)",
            round(pcr_v, 2), _clamp((1.0 - pcr_v) / 0.4) * 100.0)

    # 3. Net delta-exposure tilt.
    denom = gex_totals["call_dex"] + abs(gex_totals["put_dex"])
    if denom > 0:
        tilt = gex_totals["net_dex"] / denom
        add("direction", "dex_tilt", "Delta exposure tilt",
            round(tilt, 3), _clamp(tilt) * 100.0)

    # 4. VIX day change (falling VIX = risk-on).
    if vix is not None and vix.change_pct is not None:
        add("volatility", "vix_change", "VIX day change %",
            round(vix.change_pct, 2), _clamp(vix.change_pct / 5.0) * 100.0)

    # 5. Put/Call OI ratio. Index baseline ~1.2 neutral.
    if gex_totals["call_oi"] > 0:
        pcr_oi = gex_totals["put_oi"] / gex_totals["call_oi"]
        add("direction", "pcr_oi", "Put/Call ratio (OI)",
            round(pcr_oi, 2), _clamp((1.2 - pcr_oi) / 0.5) * 100.0)

    # 6. 25-delta IV skew (~30 DTE). ~4 pts is typical for index puts.
    skew = iv_skew_25d(chain.contracts, today)
    if skew is not None:
        add("volatility", "iv_skew", "25Δ IV skew (pts)",
            round(skew, 2), _clamp((skew - 4.0) / 3.0) * 100.0)

    # 7. Underlying day momentum.
    if chain.change_pct is not None:
        add("direction", "price_momentum", "Price day change %",
            round(chain.change_pct, 2), _clamp(chain.change_pct / 1.0) * 100.0)

    # 8. IV30 day change (vol bid = defensive).
    if chain.iv30_change_pct is not None:
        add("volatility", "iv30_change", "IV30 day change %",
            round(chain.iv30_change_pct, 2),
            _clamp(chain.iv30_change_pct / 8.0) * 100.0)

    def aggregate(components: list, weights: dict, labels: tuple[str, ...]) -> dict:
        available_weight = sum(c["weight"] for c in components)
        score = (sum(c["score"] * c["weight"] for c in components)
                 / available_weight if available_weight else None)
        for c in components:
            effective = c["weight"] / available_weight if available_weight else 0.0
            c["effective_weight"] = round(effective, 3)
            c["contribution"] = round(c["score"] * effective, 1)
        if score is None:
            label = "Insufficient data"
        elif score >= 50:
            label = labels[0]
        elif score >= 15:
            label = labels[1]
        elif score > -15:
            label = labels[2]
        elif score > -50:
            label = labels[3]
        else:
            label = labels[4]
        coverage = available_weight / sum(weights.values())
        confidence = "Medium" if coverage >= 0.85 else "Low" if coverage >= 0.6 else "Insufficient"
        return {"score": round(score, 1) if score is not None else None,
                "label": label, "components": components,
                "coverage_pct": round(coverage * 100.0),
                "confidence": confidence}

    direction = aggregate(
        direction_components, config.DIRECTION_WEIGHTS,
        ("Strong bullish pressure", "Bullish pressure", "Mixed",
         "Bearish pressure", "Strong bearish pressure"),
    )
    volatility = aggregate(
        volatility_components, config.VOLATILITY_WEIGHTS,
        ("High instability", "Elevated instability", "Balanced",
         "Stable", "Very stable"),
    )

    missing = []
    present = {c["name"] for c in direction_components + volatility_components}
    for name, label in (
        ("gamma_regime", "gamma flip"), ("vix_change", "VIX change"),
        ("iv30_change", "IV30 change"), ("iv_skew", "25-delta skew"),
        ("price_momentum", "price change"), ("pcr_volume", "put/call volume"),
        ("dex_tilt", "delta exposure"), ("pcr_oi", "put/call open interest"),
    ):
        if name not in present:
            missing.append(label)
    confidence_rank = {"Insufficient": 0, "Low": 1, "Medium": 2}
    confidence_level = min(
        (direction["confidence"], volatility["confidence"]),
        key=lambda value: confidence_rank[value],
    )
    disclosures = [
        "CBOE options quotes are delayed by about 15 minutes.",
        "Dealer positioning is estimated from open interest, not observed.",
        "Put/call volume is unsigned and does not identify buyers or sellers.",
        "Market-state reference only; predictive performance is not validated.",
    ]
    if missing:
        disclosures.append("Missing inputs: " + ", ".join(missing) + ".")

    nearest = min({c.expiry for c in chain.contracts}) if chain.contracts else None
    mp = max_pain(chain.contracts, nearest) if nearest else None

    return {
        # Legacy aliases retain API compatibility; they now reflect direction.
        "score": direction["score"],
        "label": direction["label"],
        "components": direction_components + volatility_components,
        "direction": direction,
        "volatility": volatility,
        "confidence": {
            "level": confidence_level,
            "missing_inputs": missing,
            "disclosures": disclosures,
        },
        "metrics": {
            "vix": round(vix.level, 2) if vix else None,
            "vix_change_pct": (round(vix.change_pct, 2)
                               if vix and vix.change_pct is not None else None),
            "iv30": round(chain.iv30, 2) if chain.iv30 is not None else None,
            "iv30_change_pct": (round(chain.iv30_change_pct, 2)
                                if chain.iv30_change_pct is not None else None),
            "max_pain": mp,
            "max_pain_expiry": nearest.isoformat() if nearest else None,
            "zero_dte_share_pct": zero_dte_share,
            "net_gex_bn": round(gex_totals["net_gex"] / BN, 2),
            "regime": "positive" if gex_totals["net_gex"] >= 0 else "negative",
            "flip": flip,
            "flip_dist_pct": round((spot - flip) / spot * 100.0, 2) if flip and spot else None,
            "pcr_vol": round(gex_totals["put_vol"] / gex_totals["call_vol"], 2)
                       if gex_totals["call_vol"] else None,
            "pcr_oi": round(gex_totals["put_oi"] / gex_totals["call_oi"], 2)
                      if gex_totals["call_oi"] else None,
        },
    }
