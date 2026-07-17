"""Shared application services used by REST and MCP transports."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from . import config
from .cache import SnapshotCache
from .engine import snapshot as snapshot_engine
from .engine.snapshot import VixCache

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self) -> None:
        self.client: Optional[httpx.AsyncClient] = None
        self.cache = SnapshotCache()
        self.vix_cache = VixCache()
        self._warm_task: Optional[asyncio.Task] = None

    async def start(self, prewarm: bool = True) -> None:
        timeout = httpx.Timeout(connect=config.FETCH_CONNECT_TIMEOUT,
                                read=config.FETCH_READ_TIMEOUT,
                                write=5.0, pool=5.0)
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": config.USER_AGENT},
            follow_redirects=True,
        )
        if prewarm:
            self._warm_task = asyncio.create_task(self._prewarm())

    async def _prewarm(self) -> None:
        try:
            await self.get_bundle()
            log.info("SPX snapshot prewarm complete")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A failed warmup must not prevent the web process from starting;
            # the normal request path will retry through the cache builder.
            log.warning("SPX snapshot prewarm failed: %s", exc)

    async def close(self) -> None:
        if self._warm_task is not None and not self._warm_task.done():
            self._warm_task.cancel()
            try:
                await self._warm_task
            except asyncio.CancelledError:
                pass
        self._warm_task = None
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def get_bundle(self):
        if self.client is None:
            raise RuntimeError("application services are not running")
        return await self.cache.get(
            "SPX",
            lambda: snapshot_engine.build_snapshot(self.client, self.vix_cache),
        )


runtime = Runtime()
