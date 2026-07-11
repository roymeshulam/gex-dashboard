"""Shared application services used by REST and MCP transports."""
from __future__ import annotations

from typing import Optional

import httpx

from . import config
from .cache import SnapshotCache
from .engine import snapshot as snapshot_engine
from .engine.snapshot import VixCache


class Runtime:
    def __init__(self) -> None:
        self.client: Optional[httpx.AsyncClient] = None
        self.cache = SnapshotCache()
        self.vix_cache = VixCache()

    async def start(self) -> None:
        timeout = httpx.Timeout(connect=config.FETCH_CONNECT_TIMEOUT,
                                read=config.FETCH_READ_TIMEOUT,
                                write=5.0, pool=5.0)
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": config.USER_AGENT},
            follow_redirects=True,
        )

    async def close(self) -> None:
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
