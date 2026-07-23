"""Snapshot orchestrator: fetch chain -> compute every view once -> small
JSON-ready bundle. The raw ~25MB chain JSON is discarded immediately; only
the ~300KB computed bundle is cached.

A module-level semaphore prevents overlapping refreshes of the large chain.
"""
from __future__ import annotations

import asyncio
import datetime
import logging

import httpx

from .. import config, market
from ..providers import cboe
from . import flow as flow_engine
from . import gex as gex_engine
from . import greeks as greeks_engine
from . import sentiment as sentiment_engine

log = logging.getLogger(__name__)

FETCH_SEMAPHORE = asyncio.Semaphore(1)


async def build_snapshot(client: httpx.AsyncClient) -> dict:
    cfg = config.SPX

    async def fetch_chain_once():
        async with FETCH_SEMAPHORE:
            return await cboe.fetch_chain(client)

    async def fetch_vix_once():
        try:
            return await cboe.fetch_vix(client)
        except cboe.CboeError as error:
            log.warning("VIX fetch failed: %s", error)
            return None

    # Both requests are independent. Starting them together removes the VIX
    # round trip from the cold snapshot's critical path.
    chain, vix = await asyncio.gather(fetch_chain_once(), fetch_vix_once())

    spot = chain.spot
    today = market.today_expiry_date()
    contracts = chain.contracts

    gex_totals = gex_engine.totals(contracts, spot)
    all_profile = gex_engine.strike_profile(contracts, spot)
    call_wall, put_wall = gex_engine.find_walls(all_profile)
    flip = gex_engine.find_gamma_flip(contracts, spot, chain.last_trade_time)
    flip_r = round(flip, 2) if flip is not None else None

    heatmap = gex_engine.build_heatmap(contracts, spot, cfg)
    strikemap = gex_engine.build_strikemap(
        contracts, spot, cfg, as_of=chain.last_trade_time, today=today)
    levels = gex_engine.build_expiry_levels(
        contracts, spot, as_of=chain.last_trade_time)
    zerodte = gex_engine.build_zero_dte(
        contracts, spot, cfg, today, as_of=chain.last_trade_time)
    flow = flow_engine.build_flow(contracts, spot, cfg, today=today)
    expected_ranges = flow_engine.build_expected_ranges(
        contracts, spot, levels, today)
    greeks = greeks_engine.build_surface(contracts, spot, today)
    zshare = zerodte["stats"]["dte_share_pct"] if zerodte.get("available") else 0.0
    senti = sentiment_engine.compute_sentiment(
        chain, gex_totals, flip_r, vix, today, zshare)

    status = {
        "spot": round(spot, 2),
        "change_pct": round(chain.change_pct, 2) if chain.change_pct is not None else None,
        "total_gex_bn": round(gex_totals["net_gex"] / gex_engine.BN, 2),
        "regime": "positive" if gex_totals["net_gex"] >= 0 else "negative",
        "flip": flip_r,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "call_dex_bn": round(gex_totals["call_dex"] / gex_engine.BN, 2),
        "put_dex_bn": round(gex_totals["put_dex"] / gex_engine.BN, 2),
        "net_dex_bn": round(gex_totals["net_dex"] / gex_engine.BN, 2),
        "pcr_vol": round(gex_totals["put_vol"] / gex_totals["call_vol"], 2)
                   if gex_totals["call_vol"] else None,
        "iv30": round(chain.iv30, 2) if chain.iv30 is not None else None,
        "sentiment_score": senti["score"],
        "sentiment_label": senti["label"],
        "direction_score": senti["direction"]["score"],
        "direction_label": senti["direction"]["label"],
        "volatility_score": senti["volatility"]["score"],
        "volatility_label": senti["volatility"]["label"],
        "confidence": senti["confidence"]["level"],
        "n_contracts": len(contracts),
    }

    return {
        # SnapshotCache uses the upstream payload timestamp so its hourly
        # lifetime stays synchronized with the CBOE disk cache across restarts.
        "_source_fetched_at": chain.source_fetched_at or chain.data_ts.timestamp(),
        "status": status,
        "heatmap": heatmap,
        "strikemap": strikemap,
        "levels": levels,
        "flow": flow,
        "expected_ranges": expected_ranges,
        "volatility": {
            "term_structure": flow["term_structure"],
            "expected_move_term_structure": flow["expected_move_term_structure"],
        },
        "greeks": {
            "expiries": greeks["expiries"],
            "by_expiry": greeks["by_expiry"],
        },
        "_greeks_surface": greeks,
        "sentiment": senti,
        "zerodte": zerodte,
        "meta": {
            "data_timestamp": chain.data_ts.isoformat(),
            "last_trade_time": chain.last_trade_time.isoformat(),
            "fetched_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            "freshness": market.freshness(chain.last_trade_time),
        },
    }
