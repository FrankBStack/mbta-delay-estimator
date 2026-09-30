"""Compute where each stop sits along its trip's shape.

GTFS has a field for this (shape_dist_traveled) but the MBTA leaves it blank on
every shape point, so it is derived here with ST_LineLocatePoint.

Keyed on (shape_id, stop_id) rather than (trip_id, stop_sequence): 122k trips
share 1,147 shapes, so this is ~24k geometry operations instead of 3.2M.

    python -m app.offsets
"""

import asyncio
import time
from typing import Any

import asyncpg

from . import db


async def build(conn: asyncpg.Connection) -> dict[str, Any]:
    """Fill trip_stop_offset from trip, stop_time, shape and stop, whichever
    schema the connection's search_path resolves them in."""
    print("computing stop offsets along shapes")
    started = time.monotonic()

    await conn.execute("TRUNCATE trip_stop_offset")

    await conn.execute(
        """
        CREATE TEMP TABLE shape_stop AS
        SELECT DISTINCT t.shape_id, st.stop_id
        FROM trip t
        JOIN stop_time st ON st.trip_id = t.trip_id
        WHERE t.shape_id IS NOT NULL
        """
    )
    pairs = await conn.fetchval("SELECT count(*) FROM shape_stop")
    print(f"  {pairs:,} distinct (shape, stop) pairs")

    # geom_p, not geom: locating a point on a line in raw lat/lon degrees drags
    # the answer east-west, since a degree of longitude is only ~0.74 of a
    # degree of latitude up here.
    await conn.execute(
        """
        CREATE TEMP TABLE shape_stop_frac AS
        SELECT ss.shape_id,
               ss.stop_id,
               ST_LineLocatePoint(sh.geom_p, s.geom_p)      AS frac,
               ST_Distance(sh.geom_p, s.geom_p)             AS snap_error_m
        FROM shape_stop ss
        JOIN shape sh ON sh.shape_id = ss.shape_id
        JOIN stop  s  ON s.stop_id   = ss.stop_id
        """
    )
    await conn.execute("CREATE INDEX ON shape_stop_frac (shape_id, stop_id)")
    print(f"  located in {time.monotonic()-started:.1f}s")

    await conn.execute(
        """
        INSERT INTO trip_stop_offset
            (trip_id, stop_sequence, stop_id, frac, arrival_s, departure_s)
        SELECT st.trip_id, st.stop_sequence, st.stop_id, f.frac,
               st.arrival_s, st.departure_s
        FROM stop_time st
        JOIN trip t ON t.trip_id = st.trip_id
        JOIN shape_stop_frac f
          ON f.shape_id = t.shape_id AND f.stop_id = st.stop_id
        WHERE t.shape_id IS NOT NULL
        """
    )

    await conn.execute("ANALYZE trip_stop_offset")

    # Loop routes pass the same point twice and ST_LineLocatePoint only ever
    # returns the first match, so their fractions jump backwards. Counted
    # here so a load says how much of the feed that is; delay.py checks it
    # per leg when it places a vehicle
    stats = await conn.fetchrow(
        """
        WITH stepped AS (
            SELECT trip_id, frac,
                   lag(frac) OVER (PARTITION BY trip_id ORDER BY stop_sequence) AS prev
            FROM trip_stop_offset
        ),
        trips AS (
            SELECT trip_id, bool_and(frac >= prev - 1e-9) AS mono
            FROM stepped WHERE prev IS NOT NULL GROUP BY trip_id
        )
        SELECT (SELECT count(*) FROM trip_stop_offset)               AS rows,
               (SELECT count(*) FROM trips)                          AS trips,
               (SELECT count(*) FROM trips WHERE NOT mono)           AS non_monotonic,
               round(avg(snap_error_m)::numeric, 1)                  AS mean_snap_m,
               round(percentile_cont(0.95) WITHIN GROUP (ORDER BY snap_error_m)::numeric, 1)
                                                                     AS p95_snap_m,
               round(max(snap_error_m)::numeric, 1)                  AS max_snap_m
        FROM shape_stop_frac
        """
    )
    r = dict(stats)
    print(f"  {r['rows']:,} offsets over {r['trips']:,} trips"
          f" in {time.monotonic()-started:.1f}s")
    print(f"  snap error: mean {r['mean_snap_m']}m,"
          f" p95 {r['p95_snap_m']}m, max {r['max_snap_m']}m")
    pct = 100.0 * r["non_monotonic"] / max(r["trips"], 1)
    print(f"  {r['non_monotonic']:,} trips ({pct:.1f}%) non-monotonic")
    return r


if __name__ == "__main__":
    async def _main() -> None:
        pool = await db.connect()
        try:
            async with pool.acquire() as conn:
                await build(conn)
        finally:
            await db.close()

    asyncio.run(_main())
