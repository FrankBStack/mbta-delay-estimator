"""Delay analytics.

Low-confidence observations are excluded unless you ask for them: those are the
ones where the vehicle was too far off its shape to place, or where the numbers
came out implausible enough to suggest the wrong service date.

Vehicles waiting at, or still heading to, their origin ahead of departure are
excluded from every aggregate. They read as exactly zero, which says nothing
about lateness and drags a fleet median toward "on time".
"""

import shutil
from typing import Any

from fastapi import APIRouter, Query

from .. import cache, db
from ..services import realtime

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

CONFIDENCE_FILTER = (
    "d.confidence = ANY($2::text[])"
    " AND NOT (d.method IN ('layover', 'first_stop') AND d.computed_delay_s = 0)"
)


def _levels(include_low: bool) -> list[str]:
    return ["high", "medium", "low"] if include_low else ["high", "medium"]


@router.get("/delay-by-route")
async def delay_by_route(
    minutes: int = Query(60, ge=5, le=1440),
    route_type: int | None = Query(None, ge=0, le=7),
    min_observations: int = Query(3, ge=1, le=1000),
    include_low_confidence: bool = False,
) -> dict[str, Any]:
    return await cache.get_or_set(
        ("delay-by-route", minutes, route_type, min_observations, include_low_confidence),
        lambda: _delay_by_route(minutes, route_type, min_observations, include_low_confidence),
        ttl_s=ANALYTICS_TTL_S,
    )


async def _delay_by_route(
    minutes: int, route_type: int | None, min_observations: int, include_low_confidence: bool
) -> dict[str, Any]:
    # mean_divergence_s only averages rows where both numbers exist, so it's a
    # like-for-like difference rather than the difference of two means
    rows = await db.pool().fetch(
        f"""
        SELECT d.route_id,
               r.route_short_name, r.route_long_name, r.route_type, r.route_color,
               count(*)                                        AS observations,
               count(DISTINCT d.vehicle_id)                    AS vehicles,
               round(avg(d.computed_delay_s))::int             AS mean_computed_s,
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY d.computed_delay_s))::int
                                                               AS median_computed_s,
               round(percentile_cont(0.9) WITHIN GROUP (ORDER BY d.computed_delay_s))::int
                                                               AS p90_computed_s,
               round(avg(d.feed_delay_s) FILTER (WHERE d.feed_delay_s IS NOT NULL))::int
                                                               AS mean_feed_s,
               round(avg(d.divergence_s) FILTER (WHERE d.divergence_s IS NOT NULL))::int
                                                               AS mean_divergence_s,
               count(*) FILTER (WHERE d.divergence_s IS NOT NULL) AS compared,
               round(100.0 * count(*) FILTER (WHERE d.computed_delay_s >= 300)
                     / count(*))::int                          AS pct_over_5min
        FROM delay_observation d
        JOIN route r ON r.route_id = d.route_id
        WHERE d.ts > now() - ($1 || ' minutes')::interval
          AND {CONFIDENCE_FILTER}
          AND ($3::int IS NULL OR r.route_type = $3::int)
        GROUP BY d.route_id, r.route_short_name, r.route_long_name,
                 r.route_type, r.route_color
        HAVING count(*) >= $4
        ORDER BY avg(d.computed_delay_s) DESC
        """,
        str(minutes),
        _levels(include_low_confidence),
        route_type,
        min_observations,
    )
    return {
        "window_minutes": minutes,
        "routes": [
            {
                "route_id": r["route_id"],
                "name": r["route_short_name"] or r["route_long_name"],
                "route_type": r["route_type"],
                "color": f"#{r['route_color']}" if r["route_color"] else "#888888",
                "observations": r["observations"],
                "vehicles": r["vehicles"],
                "mean_computed_s": r["mean_computed_s"],
                "median_computed_s": r["median_computed_s"],
                "p90_computed_s": r["p90_computed_s"],
                "mean_feed_s": r["mean_feed_s"],
                "mean_divergence_s": r["mean_divergence_s"],
                "compared": r["compared"],
                "pct_over_5min": r["pct_over_5min"],
            }
            for r in rows
        ],
    }


@router.get("/divergence")
async def divergence(
    minutes: int = Query(60, ge=5, le=1440),
    include_low_confidence: bool = False,
) -> dict[str, Any]:
    """How closely our number tracks the MBTA's. Read the spread and the share
    within 60s first. Correlation is reported but is a weak test here: both
    figures share the same schedule baseline and vehicle position, and delays
    span several minutes, so a high r is nearly guaranteed.

    Thinned to one observation per vehicle per minute. Consecutive 15s reports
    from the same vehicle are near-duplicates and would overstate the sample."""
    return await cache.get_or_set(
        ("divergence", minutes, include_low_confidence),
        lambda: _divergence(minutes, include_low_confidence),
        ttl_s=ANALYTICS_TTL_S,
    )


# The page polls analytics every 30s, so a shorter cache just re-runs the
# window scan for nothing.
ANALYTICS_TTL_S = 30

# A hash aggregate over the window, then a PK join back: far cheaper than a
# DISTINCT ON sort of every row in the window. The join side repeats the time
# bound so the planner reads the window through the ts index instead of
# hashing the whole table; that alone halves the query on a small box.
THINNED = f"""
    SELECT d.*
    FROM (
        SELECT max(d.id) AS id
        FROM delay_observation d
        WHERE d.ts > now() - ($1 || ' minutes')::interval
          AND {CONFIDENCE_FILTER}
        GROUP BY d.vehicle_id, date_trunc('minute', d.ts)
    ) k
    JOIN delay_observation d
      ON d.id = k.id AND d.ts > now() - ($1 || ' minutes')::interval
"""


async def _divergence(minutes: int, include_low_confidence: bool) -> dict[str, Any]:
    row = await db.pool().fetchrow(
        f"""
        WITH d AS ({THINNED})
        SELECT count(*)                                          AS observations,
               count(*) FILTER (WHERE d.divergence_s IS NOT NULL) AS compared,
               round(avg(d.computed_delay_s))::int                AS mean_computed_s,
               round(avg(d.feed_delay_s) FILTER (WHERE d.feed_delay_s IS NOT NULL))::int
                                                                  AS mean_feed_s,
               round(avg(d.divergence_s) FILTER (WHERE d.divergence_s IS NOT NULL))::int
                                                                  AS mean_divergence_s,
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY d.divergence_s))::int
                                                                  AS median_divergence_s,
               round(stddev_pop(d.divergence_s))::int             AS stddev_divergence_s,
               round(percentile_cont(0.1) WITHIN GROUP (ORDER BY d.divergence_s))::int
                                                                  AS p10_divergence_s,
               round(percentile_cont(0.9) WITHIN GROUP (ORDER BY d.divergence_s))::int
                                                                  AS p90_divergence_s,
               round(corr(d.computed_delay_s, d.feed_delay_s)::numeric, 4) AS correlation,
               count(*) FILTER (WHERE abs(d.divergence_s) <= 60)  AS within_60s,
               count(*) FILTER (WHERE abs(d.divergence_s) <= 120) AS within_120s
        FROM d
        """,
        str(minutes),
        _levels(include_low_confidence),
    )

    by_method = await db.pool().fetch(
        f"""
        WITH d AS ({THINNED})
        SELECT d.method,
               count(*)                                           AS observations,
               round(avg(d.divergence_s) FILTER (WHERE d.divergence_s IS NOT NULL))::int
                                                                  AS mean_divergence_s,
               round(avg(abs(d.divergence_s)) FILTER (WHERE d.divergence_s IS NOT NULL))::int
                                                                  AS mean_abs_divergence_s,
               round(avg(d.snap_error_m)::numeric, 1)             AS mean_snap_error_m
        FROM d
        GROUP BY d.method
        ORDER BY count(*) DESC
        """,
        str(minutes),
        _levels(include_low_confidence),
    )

    result = dict(row) if row else {}
    compared = result.get("compared") or 0
    result["pct_within_60s"] = (
        round(100.0 * (result.get("within_60s") or 0) / compared, 1) if compared else None
    )
    result["pct_within_120s"] = (
        round(100.0 * (result.get("within_120s") or 0) / compared, 1) if compared else None
    )
    corr = result.get("correlation")
    result["correlation"] = float(corr) if corr is not None else None
    result["window_minutes"] = minutes
    result["by_method"] = [dict(m) for m in by_method]
    return result


@router.get("/timeline")
async def timeline(
    minutes: int = Query(180, ge=15, le=1440),
    bucket_minutes: int = Query(5, ge=1, le=60),
    route_id: str | None = None,
    include_low_confidence: bool = False,
) -> dict[str, Any]:
    return await cache.get_or_set(
        ("timeline", minutes, bucket_minutes, route_id, include_low_confidence),
        lambda: _timeline(minutes, bucket_minutes, route_id, include_low_confidence),
        ttl_s=ANALYTICS_TTL_S,
    )


async def _timeline(
    minutes: int, bucket_minutes: int, route_id: str | None, include_low_confidence: bool
) -> dict[str, Any]:
    rows = await db.pool().fetch(
        f"""
        SELECT to_timestamp(
                   floor(extract(epoch FROM d.ts) / ($3 * 60)) * ($3 * 60)
               ) AS bucket,
               count(*)                                          AS observations,
               round(avg(d.computed_delay_s))::int               AS mean_computed_s,
               round(avg(d.feed_delay_s) FILTER (WHERE d.feed_delay_s IS NOT NULL))::int
                                                                 AS mean_feed_s
        FROM delay_observation d
        WHERE d.ts > now() - ($1 || ' minutes')::interval
          AND {CONFIDENCE_FILTER}
          AND ($4::text IS NULL OR d.route_id = $4::text)
        GROUP BY 1
        ORDER BY 1
        """,
        str(minutes),
        _levels(include_low_confidence),
        bucket_minutes,
        route_id,
    )
    return {
        "bucket_minutes": bucket_minutes,
        "buckets": [
            {
                "ts": r["bucket"].isoformat(),
                "observations": r["observations"],
                "mean_computed_s": r["mean_computed_s"],
                "mean_feed_s": r["mean_feed_s"],
            }
            for r in rows
        ],
    }


@router.get("/health")
async def health() -> dict[str, Any]:
    """Diagnostics, not a probe; use /healthz for that. total_positions is
    the planner's estimate, everything else is exact over a bounded window."""
    return await cache.get_or_set(("health",), _health, ttl_s=15)


async def _health() -> dict[str, Any]:
    counts = await db.pool().fetchrow(
        """
        SELECT (SELECT count(*) FROM vehicle_position
                 WHERE ts > now() - interval '5 minutes')      AS recent_positions,
               (SELECT count(*) FROM delay_observation
                 WHERE ts > now() - interval '60 minutes')     AS recent_delays,
               -- the planner's estimate: an exact count scans the whole
               -- table, 12s for 48h of positions on the production box
               (SELECT GREATEST(reltuples, 0)::bigint FROM pg_class
                 WHERE oid = 'vehicle_position'::regclass)     AS total_positions,
               (SELECT count(*) FROM trip)                     AS trips,
               (SELECT value FROM feed_meta WHERE key = 'loaded_at') AS gtfs_loaded_at,
               (SELECT value FROM feed_meta WHERE key = 'feed_version') AS gtfs_version,
               (SELECT value FROM feed_meta WHERE key = 'feed_end_date') AS gtfs_end_date
        """
    )
    # from the database, so this reports the real poller whether it runs in
    # this process or its own
    async with db.pool().acquire() as conn:
        poller = await realtime.read_heartbeat(conn)

    # the containers share the host's root volume, so this is the disk
    # Postgres is writing to; the page warns when it runs low
    disk = shutil.disk_usage("/")

    return {
        "poller": poller or realtime.snapshot(),
        "data": dict(counts) if counts else {},
        "disk": {"free_bytes": disk.free, "total_bytes": disk.total},
    }
