"""Central configuration: symbols, windows, TTLs, sentiment weights."""
from __future__ import annotations

CBOE_BASE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{code}.json"

# Per-symbol chain config.
#   cboe_code  — path code on cdn.cboe.com (indices are underscore-prefixed)
#   roots      — OCC roots that belong to this symbol (SPX has SPXW weeklies)
#   window_pct — strike window around spot for heatmap/strike map
#   steps      — candidate bucket steps (points); smallest fitting MAX_HEATMAP_ROWS wins
SYMBOLS = {
    "SPX": {"cboe_code": "_SPX", "roots": {"SPX", "SPXW"}, "window_pct": 0.08,
            "steps": [5.0, 10.0, 25.0, 50.0, 100.0]},
    "SPY": {"cboe_code": "SPY", "roots": {"SPY"}, "window_pct": 0.10,
            "steps": [1.0, 2.0, 5.0, 10.0]},
    "QQQ": {"cboe_code": "QQQ", "roots": {"QQQ"}, "window_pct": 0.10,
            "steps": [1.0, 2.0, 5.0, 10.0]},
}
VIX_CODE = "_VIX"

CONTRACT_MULTIPLIER = 100

MAX_HEATMAP_ROWS = 55      # cap on bucketed strike rows in heatmap/strike map
MAX_EXPIRATIONS = 14       # heatmap columns
MAX_STRIKEMAP_EXPIRATIONS = 30
MAX_FLOW_EXPIRATIONS = 30
TOP_STRIKES = 5            # top +/- GEX strikes in summary tables
TOP_TRADES = 15            # top flow rows by premium

ZERO_DTE_WINDOW_PCT = 0.03
ZERO_DTE_MAX_ROWS = 40

TTL_OPEN_SEC = 30.0        # cache TTL while market is active
TTL_CLOSED_SEC = 600.0     # cache TTL when closed (data static)
VIX_TTL_SEC = 60.0

FETCH_CONNECT_TIMEOUT = 5.0
FETCH_READ_TIMEOUT = 30.0
FETCH_RETRIES = 2          # extra attempts after the first (total 3)
FETCH_BACKOFF = [0.5, 1.5]

SKEW_TARGET_DTE = 30
SKEW_TARGET_DELTA = 0.25

# Sentiment composite weights (renormalized over available components).
SENTIMENT_WEIGHTS = {
    "gamma_regime": 0.20,
    "pcr_volume": 0.15,
    "dex_tilt": 0.15,
    "vix_change": 0.15,
    "pcr_oi": 0.10,
    "iv_skew": 0.10,
    "price_momentum": 0.10,
    "iv30_change": 0.05,
}

USER_AGENT = "Mozilla/5.0 (gex-dashboard; educational; local use)"
