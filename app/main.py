"""App factory: shared httpx client, snapshot cache, gzip, static frontend."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .api.routes import router
from .cache import SnapshotCache
from .engine.snapshot import VixCache

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    timeout = httpx.Timeout(connect=config.FETCH_CONNECT_TIMEOUT,
                            read=config.FETCH_READ_TIMEOUT,
                            write=5.0, pool=5.0)
    app.state.client = httpx.AsyncClient(
        timeout=timeout, headers={"User-Agent": config.USER_AGENT},
        follow_redirects=True)
    app.state.cache = SnapshotCache()
    app.state.vix_cache = VixCache()
    try:
        yield
    finally:
        await app.state.client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="GEX Dashboard", lifespan=lifespan)
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
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
