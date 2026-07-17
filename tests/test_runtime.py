from __future__ import annotations

import pytest

from app import runtime as runtime_module


@pytest.mark.asyncio
async def test_runtime_prewarms_snapshot_cache(monkeypatch):
    calls = {"count": 0}

    async def fake_build_snapshot(_client, _vix_cache):
        calls["count"] += 1
        return {"status": {}}

    monkeypatch.setattr(runtime_module.snapshot_engine, "build_snapshot",
                        fake_build_snapshot)
    service = runtime_module.Runtime()

    await service.start(prewarm=True)
    await service._warm_task
    bundle, _meta = await service.get_bundle()
    await service.close()

    assert bundle == {"status": {}}
    assert calls["count"] == 1
