"""CBOE delayed-quotes provider: fetch, OCC parsing, normalization.

Free endpoint, no key:
  https://cdn.cboe.com/api/global/delayed_quotes/options/{code}.json
Quotes are ~15-min delayed; greeks/IV/OI/volume are included per contract.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import re
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import httpx

from .. import config
from ..models import ChainData, Contract, VixData

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

OCC_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


class CboeError(Exception):
    pass


class CboeUnavailable(CboeError):
    """Network failure / 5xx / timeout after retries."""


class CboeParseError(CboeError):
    """Response did not match the expected schema."""


class OccParseError(CboeError):
    pass


def parse_occ(occ: str) -> Tuple[str, datetime.date, str, float]:
    """'SPXW260612P07400000' -> ('SPXW', date(2026,6,12), 'P', 7400.0).

    Strike is the last 8 digits divided by 1000.
    """
    m = OCC_RE.match(occ or "")
    if not m:
        raise OccParseError(f"bad OCC symbol: {occ!r}")
    root, ymd, cp, strike_raw = m.groups()
    try:
        expiry = datetime.date(2000 + int(ymd[0:2]), int(ymd[2:4]), int(ymd[4:6]))
    except ValueError as e:
        raise OccParseError(f"bad expiry in {occ!r}: {e}")
    return root, expiry, cp, int(strike_raw) / 1000.0


def parse_et_timestamp(s: str) -> datetime.datetime:
    """Per-option / underlying 'last_trade_time' is timezone-naive US/Eastern
    ('2026-06-09T16:14:59' = the 16:15 ET close)."""
    return datetime.datetime.fromisoformat(s).replace(tzinfo=ET)


def parse_utc_timestamp(s: str) -> datetime.datetime:
    """The top-level snapshot 'timestamp' ('2026-06-09 23:04:44') is UTC —
    verified empirically: it tracks fetch time as UTC, while last_trade_time
    tracks the ET session clock."""
    return datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc)


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def normalize(raw: dict, today: Optional[datetime.date] = None) -> ChainData:
    """Raw CBOE JSON -> ChainData. Filters to SPX OCC roots, drops
    expired contracts, coerces missing numerics to 0. The (large) raw dict is
    not retained."""
    cfg = config.SPX
    try:
        data = raw["data"]
        options = data["options"]
    except (KeyError, TypeError) as e:
        raise CboeParseError(f"unexpected CBOE schema for SPX: {e}")

    spot = _f(data.get("current_price")) or _f(data.get("close")) or _f(data.get("prev_day_close"))
    if not spot:
        raise CboeParseError("no usable spot price for SPX")

    if today is None:
        today = datetime.datetime.now(tz=ET).date()

    contracts = []
    skipped = 0
    for o in options:
        try:
            root, expiry, cp, strike = parse_occ(o.get("option", ""))
        except OccParseError:
            skipped += 1
            continue
        if root not in cfg["roots"] or expiry < today:
            continue
        contracts.append(Contract(
            root=root, expiry=expiry, cp=cp, strike=strike,
            bid=_f(o.get("bid")), ask=_f(o.get("ask")),
            last=_f(o.get("last_trade_price")), iv=_f(o.get("iv")),
            oi=int(_f(o.get("open_interest"))), volume=int(_f(o.get("volume"))),
            delta=_f(o.get("delta")), gamma=_f(o.get("gamma")),
        ))
    if skipped:
        log.warning("SPX: skipped %d unparseable OCC symbols", skipped)
    if not contracts:
        raise CboeParseError("no contracts after filtering for SPX")

    try:
        data_ts = parse_utc_timestamp(raw.get("timestamp", ""))
    except ValueError:
        data_ts = datetime.datetime.now(tz=datetime.timezone.utc)
    try:
        ltt = parse_et_timestamp(data.get("last_trade_time", ""))
    except (ValueError, TypeError):
        ltt = data_ts

    return ChainData(
        symbol="SPX", spot=spot,
        change_pct=_f(data.get("price_change_percent")),
        iv30=_f(data.get("iv30")), iv30_change_pct=_f(data.get("iv30_change_percent")),
        data_ts=data_ts, last_trade_time=ltt, contracts=contracts,
    )


async def _get_json(client: httpx.AsyncClient, code: str) -> dict:
    url = config.CBOE_BASE.format(code=code)
    last_exc: Optional[Exception] = None
    for attempt in range(1 + config.FETCH_RETRIES):
        try:
            resp = await client.get(url)
            if resp.status_code >= 500:
                raise CboeUnavailable(f"CBOE {resp.status_code} for {code}")
            if resp.status_code != 200:
                raise CboeParseError(f"CBOE {resp.status_code} for {code}")
            return resp.json()
        except (httpx.TransportError, CboeUnavailable) as e:
            last_exc = e
            if attempt < config.FETCH_RETRIES:
                await asyncio.sleep(config.FETCH_BACKOFF[min(attempt, len(config.FETCH_BACKOFF) - 1)])
        except ValueError as e:  # bad JSON
            raise CboeParseError(f"CBOE bad JSON for {code}: {e}")
    raise CboeUnavailable(f"CBOE unreachable for {code}: {last_exc}")


async def fetch_chain(client: httpx.AsyncClient) -> ChainData:
    raw = await _get_json(client, config.SPX["cboe_code"])
    return normalize(raw)


async def fetch_vix(client: httpx.AsyncClient) -> VixData:
    raw = await _get_json(client, config.VIX_CODE)
    try:
        data = raw["data"]
        level = _f(data.get("current_price")) or _f(data.get("close"))
        ts = parse_utc_timestamp(raw.get("timestamp", ""))
    except (KeyError, TypeError, ValueError) as e:
        raise CboeParseError(f"unexpected VIX schema: {e}")
    if not level:
        raise CboeParseError("no usable VIX level")
    return VixData(level=level, change_pct=_f(data.get("price_change_percent")), ts=ts)
