# GEX Dashboard

[![Deploy to Render][render-badge]][render-deploy]

Free, self-hosted **SPX gamma-exposure dashboard** in the style of
spxgexheatmap.com: GEX heatmap, strike map with walls & gamma flip, 0DTE
roadmap, option flow, and a composite sentiment gauge. Mobile-friendly with a
bottom tab bar, auto-refreshing every 30 s.
The header Guide link remains available on mobile, with symbol controls
wrapping onto a second row on narrow screens.

The heatmap displays up to 14 expirations for readability. Strike Map and
Option Flow selectors include up to 30 expiration dates for longer-range
analysis.

- **Data**: free CBOE delayed quotes (`cdn.cboe.com`) — no API key, no cost.
  Quotes are ~15 min delayed; greeks (gamma/delta), IV, OI and volume are
  included per contract, so all GEX math is recomputed server-side on every
  refresh. Open interest updates each morning.
- **Stack**: FastAPI + httpx (async) backend, vanilla JS + Apache ECharts
  frontend. No database, no background workers — built for free hosting.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                                  # 40 unit tests
uvicorn app.main:app --reload --port 8000
```

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q                                  # 40 unit tests
uvicorn app.main:app --reload --port 8000
```

Open the [dashboard](http://localhost:8000) and the
[usage guide](http://localhost:8000/guide.html).

## API

- `GET /api/spx/snapshot` returns a computed snapshot. Use the
  `views` query parameter to request `heatmap`, `strikemap`, `flow`,
  `sentiment`, or `zerodte`. The response always includes `status` and `meta`.
- `GET /api/spx/levels?dte=1` returns the call wall, gamma flip, and put wall
  for an expiration. Values may be calendar DTE integers or ISO dates. Pass
  `dte` repeatedly, comma-separated, or as a JSON array to receive an array:
  `?dte=1&dte=5`, `?dte=1,5`, or `?dte=[1,5]`.
- `GET /healthz` provides a liveness check without calling the upstream API.

## MCP for LLM agents

The server also exposes a read-only Streamable HTTP MCP endpoint at `/mcp`.
Its `get_spx_gamma_levels` tool accepts one calendar DTE/ISO expiry or an array
and returns the same cached call wall, gamma flip, and put wall data as the
REST API. Tool instructions and JSON Schema are advertised during MCP tool
discovery. See [MCP.md](MCP.md) for connection configuration, input/output
examples, and agent guidance.

## How it stays free-tier friendly

No polling loop runs server-side. Snapshots are **computed on request** and
cached ~30 s (10 min when the market is closed) with stale-while-revalidate
and per-symbol locks, so a sleeping free instance wakes on the first visit,
fetches once, and every subsequent poll inside the TTL is a cache hit. The
raw ~25 MB CBOE chain is parsed under a semaphore and discarded immediately;
only the ~300 KB computed bundle stays in memory.

## Deploy free on Render

Click the **Deploy to Render** button above (or on
[render.com](https://render.com): **New → Blueprint** → pick this repo).
`render.yaml` provisions the free web service automatically. Free instances
sleep after ~15 min idle; the frontend shows a "waking the free server"
notice and recovers automatically (~30–60 s).

## Formulas (per contract)

- `GEX = ±gamma × OI × 100 × spot² × 0.01` (calls +, puts −; $ per 1% move)
- `DEX = delta × OI × 100 × spot`
- **Call/Put wall** = strike with the max positive / min negative net GEX
- **Gamma flip** = zero-crossing of aggregate GEX after each contract's gamma
  is repriced across hypothetical SPX prices
- **Market state** = separate directional-pressure and volatility-regime
  readings with missing-input coverage and explicit confidence disclosures

## Notes & limitations

- CBOE's top-level snapshot `timestamp` is UTC; per-option `last_trade_time`
  is US/Eastern. Both are handled in `app/providers/cboe.py`.
- Buy/sell flow classification is a quote-rule heuristic on delayed data —
  an estimate, not tape-true aggressor flow.
- Educational market-structure tool. **Not financial advice.**

## Production restart automation

`.github/workflows/restart-production.yml` runs after every successful push to
`main` (and can also be started manually). It connects to
`meshulro@176.57.150.218:22`, resolves the service's configured working
directory, pulls `origin/main` with `--ff-only`, restarts the user service, and
verifies its status. A failed pull, restart, or inactive service fails the
workflow.

Configure these secrets under **Settings → Secrets and variables → Actions**:

- `DEPLOY_PASSWORD` — the SSH password; never commit it to the repository.
- `DEPLOY_KNOWN_HOSTS` — the verified host-key line produced by
  `ssh-keyscan -p 22 176.57.150.218`.

The service's `WorkingDirectory` must point to the Git checkout and that
checkout must have permission to pull from `origin` non-interactively.

[render-badge]: https://render.com/images/deploy-to-render-button.svg
[render-deploy]: https://render.com/deploy?repo=https://github.com/roymeshulam/gex-dashboard
