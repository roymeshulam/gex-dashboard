"""App factory: shared httpx client, snapshot cache, gzip, static frontend."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .mcp_server import mcp
from .runtime import runtime

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await runtime.start()
    try:
        if app.state.mcp_enabled:
            async with mcp.session_manager.run():
                yield
        else:
            yield
    finally:
        await runtime.close()


def create_app(include_mcp: bool = True) -> FastAPI:
    app = FastAPI(title="GEX Dashboard", lifespan=lifespan)
    app.state.mcp_enabled = include_mcp
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def no_store_api(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    async def healthz():
        # Never touches upstream: safe for free-tier health checks.
        return {"ok": True}

    app.include_router(router)
    if include_mcp:
        @app.api_route("/mcp", methods=["GET", "POST", "DELETE"],
                       include_in_schema=False)
        async def canonical_mcp_endpoint():
            return RedirectResponse(url="/mcp/", status_code=307)

        app.mount("/mcp", mcp.streamable_http_app(), name="mcp")
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
