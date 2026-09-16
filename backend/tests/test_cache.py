"""The response cache: per-key locking and stampede protection."""

import asyncio

from app import cache


async def test_slow_key_does_not_block_other_keys():
    cache.clear()
    order = []

    async def slow():
        await asyncio.sleep(0.2)
        order.append("slow")
        return "a"

    async def fast():
        order.append("fast")
        return "b"

    a = asyncio.create_task(cache.get_or_set(("slow",), slow, ttl_s=5))
    await asyncio.sleep(0.01)
    b = asyncio.create_task(cache.get_or_set(("fast",), fast, ttl_s=5))
    assert await b == "b"
    assert await a == "a"
    assert order == ["fast", "slow"]


async def test_same_key_runs_the_producer_once():
    cache.clear()
    calls = 0

    async def producer():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return calls

    results = await asyncio.gather(*(cache.get_or_set(("k",), producer, ttl_s=5) for _ in range(5)))
    assert results == [1] * 5
    assert calls == 1
    assert not cache._locks


async def test_expired_entry_is_recomputed():
    cache.clear()
    calls = 0

    async def producer():
        nonlocal calls
        calls += 1
        return calls

    assert await cache.get_or_set(("e",), producer, ttl_s=0.01) == 1
    await asyncio.sleep(0.02)
    assert await cache.get_or_set(("e",), producer, ttl_s=0.01) == 2
