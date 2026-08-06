"""Compute where each stop sits along its trip's shape.

GTFS has a field for this (shape_dist_traveled) but the MBTA leaves it blank on
all 393,561 shape points, so it is derived here with ST_LineLocatePoint.

Keyed on (shape_id, stop_id) rather than (trip_id, stop_sequence): 87k trips
share 1,156 shapes, so this is ~24k geometry operations instead of 2.2M.

    python -m app.offsets
"""

import asyncio
import time

from . import db


async def build():
    pool = await db.connect()
    async with pool.acquire() as conn:
        return await _build(conn)


async def _build(conn):
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
               ST_Distance(sh.geom_p, s.geom_p)             AS snap_error_m,
               sh.length_m
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
            (shape_id, trip_id, stop_sequence, stop_id, frac, dist_m,
             snap_error_m, arrival_s, departure_s, frac_monotonic)
        SELECT t.shape_id, st.trip_id, st.stop_sequence, st.stop_id,
               f.frac, f.frac * f.length_m, f.snap_error_m,
               st.arrival_s, st.departure_s, true
        FROM stop_time st
        JOIN trip t ON t.trip_id = st.trip_id
        JOIN shape_stop_frac f
          ON f.shape_id = t.shape_id AND f.stop_id = st.stop_id
        WHERE t.shape_id IS NOT NULL
        """
    )

    # Loop routes pass the same point twice and ST_LineLocatePoint only ever
    # returns the first match, so their fractions jump backwards. Not corrupt
    # data, but you can't interpolate those by fraction alone.
    await conn.execute(
        """
        WITH stepped AS (
            SELECT trip_id, frac,
                   lag(frac) OVER (PARTITION BY trip_id ORDER BY stop_sequence) AS prev
            FROM trip_stop_offset
        ),
        flags AS (
            SELECT trip_id, bool_and(frac >= prev - 1e-9) AS mono
            FROM stepped WHERE prev IS NOT NULL GROUP BY trip_id
        )
        UPDATE trip_stop_offset o
        SET frac_monotonic = flags.mono
        FROM flags WHERE flags.trip_id = o.trip_id
        """
    )

    await conn.execute("ANALYZE trip_stop_offset")

    stats = await conn.fetchrow(
        """
        SELECT count(*)                                          AS rows,
               count(DISTINCT trip_id)                            AS trips,
               count(DISTINCT trip_id) FILTER (WHERE NOT frac_monotonic) AS non_monotonic,
               round(avg(snap_error_m)::numeric, 1)               AS mean_snap_m,
               round(percentile_cont(0.95) WITHIN GROUP (ORDER BY snap_error_m)::numeric, 1) AS p95_snap_m,
               round(max(snap_error_m)::numeric, 1)               AS max_snap_m
        FROM trip_stop_offset
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
    async def _main():
        try:
            await build()
        finally:
            await db.close()

    asyncio.run(_main())
