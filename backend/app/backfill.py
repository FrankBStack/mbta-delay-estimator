"""Recompute delay observations from stored positions.

    python -m app.backfill              # last BACKFILL_HOURS
    python -m app.backfill --hours 6

For after a change to the estimator, or a feed reload: the positions are
already in the database, so there is no need to wait for new data. Safe to
run alongside the poller.
"""

import argparse
import asyncio
import time

from . import db
from .config import BACKFILL_HOURS
from .services import delay


async def run(hours: int) -> None:
    pool = await db.connect()
    try:
        async with pool.acquire() as conn:
            started = time.monotonic()
            n = await delay.backfill(conn, hours)
            print(f"recomputed {n:,} observations over {hours}h"
                  f" in {time.monotonic() - started:.1f}s")
    finally:
        await db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Recompute recent delay observations")
    ap.add_argument("--hours", type=int, default=BACKFILL_HOURS)
    asyncio.run(run(ap.parse_args().hours))


if __name__ == "__main__":
    main()
