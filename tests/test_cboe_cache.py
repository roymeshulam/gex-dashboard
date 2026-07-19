from __future__ import annotations

import os
import time

import httpx
import pytest

from app import config
from app.providers import cboe


@pytest.mark.asyncio
async def test_cboe_json_uses_fresh_disk_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CBOE_DISK_CACHE_DIR", tmp_path)
    calls = {"count": 0}

    async def handler(_request):
        calls["count"] += 1
        return httpx.Response(200, json={"data": {"current_price": 20}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await cboe._get_json(client, "_VIX")
        second = await cboe._get_json(client, "_VIX")

    assert first == second
    assert calls["count"] == 1
    assert cboe._cache_path("_VIX").exists()


@pytest.mark.asyncio
async def test_cboe_json_refreshes_cache_after_one_hour(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CBOE_DISK_CACHE_DIR", tmp_path)
    responses = iter((20, 21))

    async def handler(_request):
        return httpx.Response(200, json={"data": {"current_price": next(responses)}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await cboe._get_json(client, "_VIX")
        path = cboe._cache_path("_VIX")
        expired = time.time() - config.CBOE_DISK_CACHE_TTL_SEC - 1
        os.utime(path, (expired, expired))
        second = await cboe._get_json(client, "_VIX")

    assert first["data"]["current_price"] == 20
    assert second["data"]["current_price"] == 21
