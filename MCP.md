# SPX Gamma Levels MCP Server

This application exposes a read-only Model Context Protocol server over
Streamable HTTP. It gives LLM agents the same cached SPX expiration levels as
the REST API.

## Connection

- Production URL: `https://gex.roymeshulam.com/mcp/`
- Local URL: `http://localhost:8000/mcp`
- Transport: Streamable HTTP
- Authentication: none

Example MCP client configuration:

```json
{
  "mcpServers": {
    "spx-gamma-levels": {
      "type": "http",
      "url": "https://gex.roymeshulam.com/mcp/"
    }
  }
}
```

For clients with a CLI similar to Claude Code:

```bash
claude mcp add --transport http spx-gamma-levels https://gex.roymeshulam.com/mcp/
```

## Tool

### `get_spx_gamma_levels`

Returns the SPX call wall, gamma flip point, and put wall for one or more
expirations.

Input:

```json
{ "dte": 2 }
```

`dte` accepts any of the following:

- A non-negative integer calendar DTE. `0` means today in New York.
- An expiry date formatted as `YYYY-MM-DD`.
- An array mixing integer DTE values and ISO expiry dates.

Array example:

```json
{ "dte": [0, 2, "2026-07-17"] }
```

A scalar input returns one object. An array input returns an array in the same
order:

```json
{
  "dte": 2,
  "expiry": "2026-07-13",
  "available": true,
  "call_wall": 7600.0,
  "flip": 7540.07,
  "put_wall": 7440.0
}
```

When the requested expiration is absent from the current option chain,
`available` is `false` and all three level fields are `null`. A level may also
be `null` for an available expiration when the chain has no qualifying wall or
no cumulative GEX zero-crossing.

The source is CBOE delayed options data. Values are educational market
structure estimates, not live quotes or financial advice.

## Agent guidance

Call this tool when the user asks for SPX support/resistance structure, call or
put walls, gamma flip, or levels for specific DTEs or expiration dates. Prefer
one array call when several expirations are needed. Always mention when a
requested expiration or individual level is unavailable, and do not present
the delayed values as real-time prices.
