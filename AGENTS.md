# Repository Guidelines

## Project Structure & Module Organization

The FastAPI backend lives in `app/`. API routes are defined in `app/api/`,
CBOE integration in `app/providers/`, and calculation logic in `app/engine/`.
Shared models, caching, market-hours logic, and configuration remain at the
package root. The dependency-free browser client is under `frontend/`, split
into `js/`, `css/`, and static HTML pages. Tests mirror backend behavior in
`tests/`; reusable fixtures belong in `tests/conftest.py`, with sample payloads
in `tests/fixtures/`.

Keep financial calculations in the engine layer and HTTP concerns in routes.
Avoid putting business logic in `app/main.py` or frontend rendering code.

## Build, Test, and Development Commands

Create and activate a virtual environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run `pytest -q` for the complete test suite. Start local development with:

```powershell
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000`; the API health check is at `/healthz`. Render
deployment settings are maintained in `render.yaml`.

## Coding Style & Naming Conventions

Use four-space indentation and type hints for Python. Follow existing PEP 8
conventions: `snake_case` for functions and variables, `PascalCase` for
classes, and uppercase names for configuration constants. Keep modules focused
and prefer small pure functions for calculations. JavaScript uses two-space
indentation, semicolons, `camelCase`, and `"use strict"` inside module wrappers.
No formatter or linter is configured, so match surrounding code and keep diffs
narrow.

## Testing Guidelines

Tests use `pytest` with `pytest-asyncio` in automatic mode. Name files
`test_<area>.py` and tests `test_<behavior>`. Add deterministic unit tests for
formula changes, boundary conditions, cache behavior, and malformed upstream
data. Reuse `mk()` and shared expiry fixtures from `tests/conftest.py`. Tests
must not depend on live CBOE requests.

## Commit & Pull Request Guidelines

Recent commits use short, imperative subjects such as
`Fix startup double-refresh race`. Keep each commit focused and describe
user-visible behavior. Pull requests should include a concise summary, test
results, and linked issues when applicable. Include screenshots for heatmap,
chart, navigation, or responsive-layout changes, and call out API response
shape or configuration changes explicitly.

## Security & Configuration

Do not commit credentials, local virtual environments, logs, or downloaded
market data. Preserve upstream timeouts, retry limits, and cache behavior
unless the change is intentional and tested.
