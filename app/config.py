"""Central configuration: SPX windows, TTLs, and sentiment weights."""
from __future__ import annotations

import os
from pathlib import Path

CBOE_BASE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{code}.json"
CBOE_DISK_CACHE_DIR = Path(os.getenv(
    "CBOE_DISK_CACHE_DIR",
    Path(__file__).resolve().parent.parent / ".cache" / "cboe",
))
CBOE_DISK_CACHE_TTL_SEC = 3600.0

# The SPX chain includes standard SPX contracts and SPXW weeklies.
SPX = {
    "cboe_code": "_SPX",
    "roots": {"SPX", "SPXW"},
    "window_pct": 0.08,
    "steps": [5.0, 10.0, 25.0, 50.0, 100.0],
}
VIX_CODE = "_VIX"

CONTRACT_MULTIPLIER = 100

MAX_HEATMAP_ROWS = 55      # cap on bucketed strike rows in heatmap/strike map
MAX_EXPIRATIONS = 14       # heatmap columns
TOP_STRIKES = 5            # top +/- GEX strikes in summary tables
TOP_TRADES = 15            # top flow rows by premium

ZERO_DTE_WINDOW_PCT = 0.03
ZERO_DTE_MAX_ROWS = 40

TTL_OPEN_SEC = 30.0        # cache TTL while market is active
TTL_CLOSED_SEC = 600.0     # cache TTL when closed (data static)

FETCH_CONNECT_TIMEOUT = 5.0
FETCH_READ_TIMEOUT = 30.0
FETCH_RETRIES = 2          # extra attempts after the first (total 3)
FETCH_BACKOFF = [0.5, 1.5]

SKEW_TARGET_DTE = 30
SKEW_TARGET_DELTA = 0.25

# Separate market-state weights (renormalized over available components).
DIRECTION_WEIGHTS = {
    "price_momentum": 0.40,
    "pcr_volume": 0.25,
    "dex_tilt": 0.20,
    "pcr_oi": 0.15,
}

VOLATILITY_WEIGHTS = {
    "gamma_regime": 0.40,
    "vix_change": 0.25,
    "iv30_change": 0.20,
    "iv_skew": 0.15,
}

USER_AGENT = "Mozilla/5.0 (gex-dashboard; educational; local use)"
