import pathlib

import asyncpg

from .config import DATABASE_URL, DB_POOL_MAX, DB_POOL_MIN

_pool: asyncpg.Pool | None = None

SCHEMA_PATH = pathlib.Path(__file__).with_name("schema.sql")


async def connect(min_size: int = DB_POOL_MIN, max_size: int = DB_POOL_MAX) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=min_size, max_size=max_size)
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("no pool; call connect() first")
    return _pool


async def apply_schema(conn: asyncpg.Connection) -> None:
    """Drops and recreates the static tables. The realtime tables are
    IF NOT EXISTS and survive, so a feed reload keeps the observation history."""
    await conn.execute(SCHEMA_PATH.read_text())
