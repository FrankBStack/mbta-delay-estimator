import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import CORS_ORIGINS, ENABLE_DOCS, RUN_POLLER
from .routers import analytics, routes, vehicles
from .services import realtime, scoring

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
# two lines per poll for the feed fetches alone; the poll summary already says
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("tracker")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await db.connect()
    await db.ensure_realtime_schema()

    if not await db.pool().fetchval("SELECT count(*) FROM trip_stop_offset"):
        log.warning("trip_stop_offset is empty - run `python -m app.gtfs_static` "
                    "first or nothing will have a delay")

    tasks: list[asyncio.Task[None]] = []
    if RUN_POLLER:
        tasks = [
            asyncio.create_task(realtime.run_forever(), name="gtfs-rt-poller"),
            asyncio.create_task(scoring.run_forever(), name="arrival-scoring"),
        ]
        log.info("poller started")
    else:
        log.info("poller disabled; expecting `python -m app.poller` elsewhere")

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await db.close()
        log.info("shut down")


app = FastAPI(
    title="Transit Tracker",
    description="Live MBTA vehicles, with delays computed from position against "
                "the static schedule and compared to the agency's predictions.",
    version="1.0.0",
    lifespan=lifespan,
    # an API should 404 a wrong path, not redirect
    redirect_slashes=False,
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(vehicles.router)
app.include_router(routes.router)
app.include_router(analytics.router)


@app.get("/")
async def root() -> dict[str, str | None]:
    return {"service": "transit-tracker", "docs": "/docs" if ENABLE_DOCS else None}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Load-balancer probe. /api/analytics/health counts rows and is far too
    expensive to poll."""
    await db.pool().fetchval("SELECT 1")
    return {"status": "ok"}
