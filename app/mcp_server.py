"""Model Context Protocol tools for SPX gamma levels."""
from __future__ import annotations

from typing import Union

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from . import market
from .api.routes import _level_response, _resolve_expiries
from .runtime import runtime

LevelInput = Union[int, str]

mcp = FastMCP(
    "SPX Gamma Levels",
    instructions=(
        "Use get_spx_gamma_levels to retrieve the SPX call wall, gamma flip, "
        "and put wall for one or more expirations. DTE means calendar days "
        "from the current New York date. Values come from delayed CBOE data "
        "and are educational, not financial advice."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[
            "gex.roymeshulam.com",
            "localhost:*",
            "127.0.0.1:*",
        ],
        allowed_origins=[
            "https://gex.roymeshulam.com",
            "https://chatgpt.com",
            "https://chat.openai.com",
            "http://localhost:*",
            "http://127.0.0.1:*",
        ],
    ),
)


@mcp.tool(
    title="Get SPX gamma levels",
    description=(
        "Get SPX call wall, gamma flip point, and put wall for one expiration "
        "or an array of expirations. Pass each expiration as a non-negative "
        "calendar DTE integer (0 means today) or an ISO date in YYYY-MM-DD "
        "format. The result includes the resolved DTE and expiry. available=false "
        "means that expiry is not present in the current CBOE chain; unavailable "
        "levels are null. A single input returns one object and an array input "
        "returns an array in the same order."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def get_spx_gamma_levels(
    dte: Union[LevelInput, list[LevelInput]],
) -> Union[dict, list[dict]]:
    """Retrieve SPX gamma levels for calendar DTE values or expiry dates."""
    is_array = isinstance(dte, list)
    values = dte if is_array else [dte]
    try:
        requested = _resolve_expiries([str(value) for value in values],
                                      market.today_expiry_date())
    except HTTPException as e:
        raise ValueError(str(e.detail)) from e

    bundle, _cache_meta = await runtime.get_bundle()
    result = [_level_response(bundle, days, expiry)
              for days, expiry in requested]
    return result if is_array else result[0]
