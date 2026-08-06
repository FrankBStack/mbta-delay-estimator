"""Run the GTFS-realtime poller on its own.

    python -m app.poller

Set RUN_POLLER=false on the API processes when using this, or every replica
polls and writes the same rows.
"""

import asyncio
import contextlib
import logging

from . import db
from .services import realtime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tracker.poller")


async def main():
    await db.connect()
    if not await db.pool().fetchval("SELECT count(*) FROM trip_stop_offset"):
        log.warning("trip_stop_offset is empty - run `python -m app.gtfs_static` "
                    "first or nothing will have a delay")
    log.info("poller started")
    try:
        await realtime.run_forever()
    finally:
        await db.close()
        log.info("shut down")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
