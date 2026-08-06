import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import CORS_ORIGINS, ENABLE_DOCS, RUN_POLLER
from .routers import analytics, routes, vehicles
from .services import realtime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tracker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()

    if not await db.pool().fetchval("SELECT count(*) FROM trip_stop_offset"):
        log.warning("trip_stop_offset is empty - run `python -m app.gtfs_static` "
                    "first or nothing will have a delay")

    poller = None
    if RUN_POLLER:
        poller = asyncio.create_task(realtime.run_forever(), name="gtfs-rt-poller")
        log.info("poller started")
    else:
        log.info("poller disabled; expecting `python -m app.poller` elsewhere")

    try:
        yield
    finally:
        if poller is not None:
            poller.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poller
        await db.close()
        log.info("shut down")


app = FastAPI(
    title="Transit Tracker",
    description="Live MBTA vehicles, with delays computed from position against "
                "the static schedule and compared to the agency's predictions.",
    version="1.0.0",
    lifespan=lifespan,
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
async def root():
    return {"service": "transit-tracker", "docs": "/docs" if ENABLE_DOCS else None}


@app.get("/healthz")
async def healthz():
    """Load-balancer probe. /api/analytics/health counts rows and is far too
    expensive to poll."""
    await db.pool().fetchval("SELECT 1")
    return {"status": "ok"}
