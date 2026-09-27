import pathlib

import asyncpg

from .config import DATABASE_URL, DB_POOL_MAX, DB_POOL_MIN

_pool: asyncpg.Pool | None = None

SCHEMA_PATH = pathlib.Path(__file__).with_name("schema.sql")
REALTIME_SCHEMA_PATH = pathlib.Path(__file__).with_name("schema_realtime.sql")
SCHEMA_LOCK_TIMEOUT_S = 30


async def connect(min_size: int = DB_POOL_MIN, max_size: int = DB_POOL_MAX) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=min_size,
            max_size=max_size,
            # otherwise a query outlives its process: the server only notices a
            # vanished client when it tries to reply
            server_settings={"client_connection_check_interval": "10s"},
        )
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
    """Drops and recreates the static tables, then makes sure the realtime
    tables exist. Those are IF NOT EXISTS and survive, so a feed reload keeps
    the observation history."""
    await conn.execute(SCHEMA_PATH.read_text())
    await conn.execute(REALTIME_SCHEMA_PATH.read_text())


async def ensure_realtime_schema() -> None:
    """Every statement in schema_realtime.sql is IF NOT EXISTS, so each process
    runs it at startup and a deploy that adds a realtime table or column needs
    no migration step. IF NOT EXISTS still takes each table's lock, so a stuck
    query elsewhere would hang startup silently; fail and say why instead."""
    async with pool().acquire() as conn:
        try:
            async with conn.transaction():
                await conn.execute(f"SET LOCAL lock_timeout = '{SCHEMA_LOCK_TIMEOUT_S}s'")
                await conn.execute(REALTIME_SCHEMA_PATH.read_text())
        except asyncpg.LockNotAvailableError as exc:
            raise RuntimeError(
                f"realtime schema check could not lock the tables in {SCHEMA_LOCK_TIMEOUT_S}s;"
                " something is holding them, see pg_stat_activity and pg_blocking_pids()"
            ) from exc
