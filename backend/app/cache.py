"""Short-lived response cache.

Nothing here can be fresher than the feed, so a few seconds of caching makes
database load a function of the poll interval instead of request volume.
"""

import asyncio
import time

from .config import CACHE_MAX_ENTRIES, CACHE_TTL_S

_entries = {}
_lock = asyncio.Lock()


def _evict(now):
    for key in [k for k, (expires, _) in _entries.items() if expires <= now]:
        del _entries[key]
    # route_id reaches this from the query string, so the key space is caller
    # controlled and needs a hard ceiling, not just expiry
    if len(_entries) > CACHE_MAX_ENTRIES:
        _entries.clear()


async def get_or_set(key, producer, ttl_s=None):
    ttl = CACHE_TTL_S if ttl_s is None else ttl_s
    if ttl <= 0:
        return await producer()

    hit = _entries.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]

    # single lock: one slow producer briefly blocks other misses, which is the
    # price of never stampeding the database on expiry
    async with _lock:
        hit = _entries.get(key)
        now = time.monotonic()
        if hit and hit[0] > now:
            return hit[1]
        value = await producer()
        _evict(now)
        _entries[key] = (time.monotonic() + ttl, value)
        return value


def clear():
    _entries.clear()
