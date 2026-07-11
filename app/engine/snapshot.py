"""Snapshot orchestrator: fetch chain -> compute every view once -> small
JSON-ready bundle. The raw ~25MB chain JSON is discarded immediately; only
the ~300KB computed bundle is cached.

A module-level semaphore prevents overlapping refreshes of the large chain.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import time
from typing import Optional

import httpx

from .. import config, market
from ..models import VixData
from ..providers import cboe
from . import flow as flow_engine
from . import gex as gex_engine
from . import sentiment as sentiment_engine

log = logging.getLogger(__name__)

FETCH_SEMAPHORE = asyncio.Semaphore(1)


class VixCache:
    """Tiny TTL cache for the VIX quote; failures degrade to None."""

    def __init__(self):
        self._vix: Optional[VixData] = None
        self._at = 0.0
        self._lock = asyncio.Lock()

    async def get(self, client: httpx.AsyncClient) -> Optional[VixData]:
        if self._vix is not None and time.time() - self._at < config.VIX_TTL_SEC:
            return self._vix
        async with self._lock:
            if self._vix is not None and time.time() - self._at < config.VIX_TTL_SEC:
                return self._vix
            try:
                self._vix = await cboe.fetch_vix(client)
                self._at = time.time()
            except cboe.CboeError as e:
                log.warning("VIX fetch failed: %s", e)
        return self._vix


async def build_snapshot(client: httpx.AsyncClient, vix_cache: VixCache) -> dict:
    cfg = config.SPX
    async with FETCH_SEMAPHORE:
        chain = await cboe.fetch_chain(client)
    vix = await vix_cache.get(client)

    spot = chain.spot
    today = market.today_expiry_date()
    contracts = chain.contracts

    gex_totals = gex_engine.totals(contracts, spot)
    all_profile = gex_engine.strike_profile(contracts, spot)
    call_wall, put_wall = gex_engine.find_walls(all_profile)
    flip = gex_engine.find_flip(all_profile, spot)
    flip_r = round(flip, 2) if flip is not None else None

    heatmap = gex_engine.build_heatmap(contracts, spot, cfg)
    strikemap = gex_engine.build_strikemap(contracts, spot, cfg)
    levels = gex_engine.build_expiry_levels(contracts, spot)
    zerodte = gex_engine.build_zero_dte(contracts, spot, cfg, today)
    flow = flow_engine.build_flow(contracts, spot, cfg)
    zshare = zerodte["stats"]["dte_share_pct"] if zerodte.get("available") else 0.0
    senti = sentiment_engine.compute_sentiment(
        chain, gex_totals, flip_r, vix, today, zshare)

    status = {
        "spot": round(spot, 2),
        "change_pct": round(chain.change_pct, 2),
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
        "iv30": round(chain.iv30, 2),
        "sentiment_score": senti["score"],
        "sentiment_label": senti["label"],
        "n_contracts": len(contracts),
    }

    return {
        "status": status,
        "heatmap": heatmap,
        "strikemap": strikemap,
        "levels": levels,
        "flow": flow,
        "sentiment": senti,
        "zerodte": zerodte,
        "meta": {
            "data_timestamp": chain.data_ts.isoformat(),
            "last_trade_time": chain.last_trade_time.isoformat(),
            "fetched_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            "freshness": market.freshness(chain.last_trade_time),
        },
    }
