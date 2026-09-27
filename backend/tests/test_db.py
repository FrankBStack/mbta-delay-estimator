"""Startup fails fast when the realtime tables are locked."""

import contextlib
import types

import asyncpg
import pytest

from app import db
from tests.conftest import TEST_URL


async def test_schema_check_fails_fast_when_a_table_is_locked(conn, monkeypatch):
    @contextlib.asynccontextmanager
    async def acquire():
        yield conn

    monkeypatch.setattr(db, "_pool", types.SimpleNamespace(acquire=acquire))
    monkeypatch.setattr(db, "SCHEMA_LOCK_TIMEOUT_S", 1)
    holder = await asyncpg.connect(TEST_URL)
    tx = holder.transaction()
    await tx.start()
    await holder.execute("LOCK TABLE trip_update IN ACCESS EXCLUSIVE MODE")
    try:
        with pytest.raises(RuntimeError, match="pg_blocking_pids"):
            await db.ensure_realtime_schema()
    finally:
        await tx.rollback()
        await holder.close()
