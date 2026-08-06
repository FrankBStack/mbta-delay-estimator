import os

from dotenv import load_dotenv

load_dotenv()


def _int(name, default):
    return int(os.getenv(name, default))


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/tracker")

GTFS_STATIC_URL = os.getenv("GTFS_STATIC_URL", "https://cdn.mbta.com/MBTA_GTFS.zip")
VEHICLE_POSITIONS_URL = os.getenv(
    "VEHICLE_POSITIONS_URL", "https://cdn.mbta.com/realtime/VehiclePositions.pb"
)
TRIP_UPDATES_URL = os.getenv(
    "TRIP_UPDATES_URL", "https://cdn.mbta.com/realtime/TripUpdates.pb"
)

POLL_INTERVAL_S = _int("POLL_INTERVAL_S", 15)
AGENCY_TZ = os.getenv("AGENCY_TZ", "America/New_York")

# NAD83 / Massachusetts Mainland, in metres. Everything that measures a
# distance goes through this rather than raw lat/lon. Change it with the city.
PROJECTED_SRID = _int("PROJECTED_SRID", 26986)

# beyond this distance from its own shape, an interpolation is not trustworthy
MAX_SNAP_ERROR_M = _int("MAX_SNAP_ERROR_M", 150)

RETENTION_HOURS = _int("RETENTION_HOURS", 48)

# trip_update has to outlive this: backfill() re-joins it for feed_delay_s.
BACKFILL_HOURS = _int("BACKFILL_HOURS", 24)

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")


def _bool(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# Off when the poller runs as its own process (`python -m app.poller`); leaving
# it on in more than one API replica means N pollers double-writing.
RUN_POLLER = _bool("RUN_POLLER", True)

ENABLE_DOCS = _bool("ENABLE_DOCS", True)

DB_POOL_MIN = _int("DB_POOL_MIN", 2)
DB_POOL_MAX = _int("DB_POOL_MAX", 10)

# Read endpoints can't be fresher than the feed anyway, so a few seconds of
# cache decouples database load from request volume.
CACHE_TTL_S = _int("CACHE_TTL_S", 5)
CACHE_MAX_ENTRIES = _int("CACHE_MAX_ENTRIES", 512)
