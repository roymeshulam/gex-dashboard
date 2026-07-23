"""API surface for the SPX snapshot views."""
from __future__ import annotations

import datetime
import json
import logging
import re

from fastapi import APIRouter, HTTPException, Query, Request

from .. import market
from ..providers.cboe import CboeError
from ..runtime import runtime
from ..engine.greeks import calculate_curves

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

VIEWS = {
    "summary", "heatmap", "strikemap", "flow", "greeks", "sentiment",
    "volatility", "zerodte", "expected_ranges",
}
NONNEGATIVE_INTEGER = re.compile(r"^\d+$")


def _envelope(bundle: dict, cache_meta: dict, views) -> dict:
    meta = dict(bundle["meta"])
    meta.update(cache_meta)
    meta["market"] = market.market_state()
    out_views = {v: bundle[v] for v in views if v in bundle}
    return {"symbol": "SPX", "meta": meta,
            "status": bundle["status"], "views": out_views}


async def _get_bundle(request: Request):
    return await runtime.get_bundle()


def _expand_dte_values(values: list[str]) -> list[str]:
    """Accept repeated, comma-separated, or JSON-array query values."""
    expanded = []
    for raw in values:
        value = raw.strip()
        if value.startswith("["):
            try:
                items = json.loads(value)
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=422,
                                    detail=f"invalid dte array: {e.msg}")
            if not isinstance(items, list):
                raise HTTPException(status_code=422, detail="dte must be a value or array")
            expanded.extend(str(item).strip() for item in items)
        else:
            expanded.extend(item.strip() for item in value.split(","))
    if not expanded or any(not item for item in expanded):
        raise HTTPException(status_code=422, detail="dte values must not be empty")
    return expanded


def _resolve_expiries(values: list[str], today: datetime.date) -> list[tuple[int, str]]:
    resolved = []
    for value in _expand_dte_values(values):
        if NONNEGATIVE_INTEGER.fullmatch(value):
            dte = int(value)
            expiry = today + datetime.timedelta(days=dte)
        else:
            try:
                expiry = datetime.date.fromisoformat(value)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"invalid dte value {value!r}; use a non-negative integer or YYYY-MM-DD",
                )
            dte = (expiry - today).days
            if dte < 0:
                raise HTTPException(status_code=422,
                                    detail=f"expiry {value!r} is before today")
        resolved.append((dte, expiry.isoformat()))
    return resolved


def _level_response(bundle: dict, dte: int, expiry: str) -> dict:
    levels = bundle["levels"].get(expiry)
    return {
        "dte": dte,
        "expiry": expiry,
        "available": levels is not None,
        "call_wall": levels["call_wall"] if levels else None,
        "flip": levels["flip"] if levels else None,
        "put_wall": levels["put_wall"] if levels else None,
    }


@router.get("/spx/snapshot")
async def snapshot(request: Request, views: str = Query(default="summary")):
    requested = {v.strip() for v in views.split(",") if v.strip()} or {"summary"}
    bad = requested - VIEWS
    if bad:
        raise HTTPException(status_code=400, detail=f"unknown views: {sorted(bad)}")

    try:
        bundle, cache_meta = await _get_bundle(request)
    except CboeError as e:
        log.error("SPX snapshot failed: %s", e)
        raise HTTPException(status_code=503, detail="upstream data unavailable")

    return _envelope(bundle, cache_meta, requested - {"summary"})


@router.get("/spx/levels")
async def expiry_levels(request: Request, dte: list[str] = Query(...)):
    requested = _resolve_expiries(dte, market.today_expiry_date())
    try:
        bundle, _cache_meta = await _get_bundle(request)
    except CboeError as e:
        log.error("SPX levels failed: %s", e)
        raise HTTPException(status_code=503, detail="upstream data unavailable")

    result = [_level_response(bundle, days, expiry)
              for days, expiry in requested]
    return result[0] if len(result) == 1 else result


@router.get("/spx/greeks")
async def greeks_curves(request: Request, expiry: str, strike: float,
                        cp: str = Query(default="C", pattern="^[CPcp]$"),
                        position: str = Query(default="long", pattern="^(long|short)$")):
    try:
        bundle, _cache_meta = await _get_bundle(request)
        return calculate_curves(bundle["_greeks_surface"], expiry, strike, cp, position)
    except CboeError as e:
        log.error("SPX Greeks calculation failed: %s", e)
        raise HTTPException(status_code=503, detail="upstream data unavailable")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
