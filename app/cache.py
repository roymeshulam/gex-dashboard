"""Per-symbol snapshot cache: TTL + stale-while-revalidate + stampede locks.

This is what makes the free-tier compute-on-request model viable:
- fresh hit  -> return immediately
- stale hit  -> return stale immediately, refresh once in the background
- cold start -> one builder runs per symbol (lock), others await the result
- builder failure with a stale entry -> serve stale, flag the error
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Dict, Optional, Tuple

from . import config, market


class _Entry:
    __slots__ = ("bundle", "fetched_at", "task", "error")

    def __init__(self, bundle: dict, fetched_at: float):
        self.bundle = bundle
        self.fetched_at = fetched_at
        self.task: Optional[asyncio.Task] = None
        self.error: Optional[str] = None


class SnapshotCache:
    def __init__(self):
        self._entries: Dict[str, _Entry] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    @staticmethod
    def ttl() -> float:
        snapshot_ttl = (config.TTL_OPEN_SEC if market.is_active_window()
                        else config.TTL_CLOSED_SEC)
        # Recomputing the snapshot while the provider can only return the same
        # hourly disk-cached chain wastes CPU and causes needless UI redraws.
        return max(snapshot_ttl, config.CBOE_DISK_CACHE_TTL_SEC)

    @staticmethod
    def _bundle_fetched_at(bundle: dict, fallback: float) -> float:
        """Anchor cache age to the CBOE payload, including after a restart."""
        value = bundle.get("_source_fetched_at")
        if isinstance(value, (int, float)) and 0.0 < value <= fallback:
            return float(value)
        return fallback

    async def get(self, key: str,
                  builder: Callable[[], Awaitable[dict]]) -> Tuple[dict, dict]:
        """Returns (bundle, meta). Raises only when there is no data at all."""
        now = time.time()
        entry = self._entries.get(key)

        if entry is not None:
            age = now - entry.fetched_at
            if age < self.ttl():
                return entry.bundle, self._meta(age, stale=False,
                                                refreshing=entry.task is not None,
                                                error=entry.error)
            # Stale: serve immediately, refresh in the background (once).
            if entry.task is None or entry.task.done():
                entry.task = asyncio.get_running_loop().create_task(
                    self._refresh(key, builder))
            return entry.bundle, self._meta(age, stale=True, refreshing=True,
                                            error=entry.error)

        # Cold start: single flight per symbol.
        async with self._lock(key):
            entry = self._entries.get(key)
            if entry is not None:
                return entry.bundle, self._meta(time.time() - entry.fetched_at,
                                                stale=False, refreshing=False,
                                                error=entry.error)
            bundle = await builder()
            now = time.time()
            fetched_at = self._bundle_fetched_at(bundle, now)
            self._entries[key] = _Entry(bundle, fetched_at)
            return bundle, self._meta(now - fetched_at, stale=False,
                                      refreshing=False, error=None)

    async def _refresh(self, key: str, builder) -> None:
        entry = self._entries.get(key)
        try:
            bundle = await builder()
        except Exception as e:  # keep serving the stale bundle
            if entry is not None:
                entry.error = f"refresh_failed: {type(e).__name__}"
                entry.task = None
            return
        if entry is not None:
            entry.bundle = bundle
            now = time.time()
            entry.fetched_at = self._bundle_fetched_at(bundle, now)
            entry.error = None
            entry.task = None
        else:
            self._entries[key] = _Entry(bundle, time.time())

    @staticmethod
    def _meta(age: float, stale: bool, refreshing: bool,
              error: Optional[str]) -> dict:
        return {"cache_age_sec": round(age, 1), "stale": stale,
                "refreshing": refreshing, "error": error}
