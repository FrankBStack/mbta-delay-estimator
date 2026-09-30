"""Run the GTFS-realtime poller on its own.

    python -m app.poller

Set RUN_POLLER=false on the API processes when using this, or every replica
polls and writes the same rows.
"""

import asyncio
import contextlib
import logging
import signal

from . import db
from .services import realtime, scoring

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
# two lines per poll for the feed fetches alone; the poll summary already says
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("tracker.poller")


async def main() -> None:
    await db.connect()
    await db.ensure_realtime_schema()
    if not await db.pool().fetchval("SELECT count(*) FROM trip_stop_offset"):
        log.warning("trip_stop_offset is empty - run `python -m app.gtfs_static` "
                    "first or nothing will have a delay")
    log.info("poller started")
    loops = asyncio.gather(realtime.run_forever(), scoring.run_forever())
    # a stop from compose cancels the loops mid-sleep rather than being
    # ignored until the kill ten seconds later
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, loops.cancel)
    try:
        with contextlib.suppress(asyncio.CancelledError):
            await loops
    finally:
        await db.close()
        log.info("shut down")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
