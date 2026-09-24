"""Short-lived response cache.

Nothing here can be fresher than the feed, so a few seconds of caching makes
database load a function of the poll interval instead of request volume.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

from .config import CACHE_MAX_ENTRIES, CACHE_TTL_S

_entries: dict[Hashable, tuple[float, Any]] = {}


# One lock per key, kept only while someone is using it. A slow analytics
# query must not hold up a miss on the vehicle poll.
class _KeyLock:
    __slots__ = ("lock", "users")

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.users = 0


_locks: dict[Hashable, _KeyLock] = {}


def _evict(now: float) -> None:
    for key in [k for k, (expires, _) in _entries.items() if expires <= now]:
        del _entries[key]
    # route_id reaches this from the query string, so the key space is caller
    # controlled and needs a hard ceiling, not just expiry. Oldest out first:
    # clearing everything would let a scanner flush the hot keys every pass
    excess = len(_entries) - CACHE_MAX_ENTRIES
    if excess > 0:
        for key in sorted(_entries, key=lambda k: _entries[k][0])[:excess]:
            del _entries[key]


async def get_or_set(
    key: Hashable, producer: Callable[[], Awaitable[Any]], ttl_s: float | None = None
) -> Any:
    ttl = CACHE_TTL_S if ttl_s is None else ttl_s
    if ttl <= 0:
        return await producer()

    hit = _entries.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]

    # misses on the same key wait for one producer rather than stampeding the
    # database on expiry; misses on other keys proceed independently
    kl = _locks.get(key)
    if kl is None:
        kl = _locks[key] = _KeyLock()
    kl.users += 1
    try:
        async with kl.lock:
            hit = _entries.get(key)
            now = time.monotonic()
            if hit and hit[0] > now:
                return hit[1]
            value = await producer()
            _entries[key] = (time.monotonic() + ttl, value)
            _evict(now)
            return value
    finally:
        kl.users -= 1
        if kl.users == 0 and _locks.get(key) is kl:
            del _locks[key]


def clear() -> None:
    _entries.clear()
    _locks.clear()
