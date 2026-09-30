"""Derive a vehicle's delay from its position, and compare it to the feed.

trip_stop_offset holds how far along a trip's shape each stop sits, which
reduces the timetable to a mapping from position to time. Projecting a live
vehicle onto the same shape inverts it: read off when the schedule expects a
vehicle at that point.

Placing a vehicle needs both the feed's current_stop_sequence and the geometry.
Sequence alone is too coarse; geometry alone fails on loop routes, where
ST_LineLocatePoint resolves a second-pass vehicle back to the start of the line.
Sequence selects the leg, the fraction locates the vehicle along it.

A vehicle on an added trip (every Green Line train) has no timetable of its
own. MATCH_SQL pins each such trip, when first seen, to the scheduled trip on
its route and direction whose timetable is nearest at the stop it is at, and
the estimator then reads that trip's timetable through the vehicle's stop ids.
That measures deviation from the nearest scheduled slot: a train that missed
its slot by a whole headway reads as on the next one.
"""

import asyncpg

from ..config import AGENCY_TZ, BACKFILL_HOURS, MAX_SNAP_ERROR_M

# Beyond this, the cause is a service-date mismatch or a mid-run reassignment
# rather than a late vehicle. Retained, but flagged low for the analytics.
IMPLAUSIBLE_DELAY_S = 3 * 3600

# A stopped vehicle is scored at the moment it arrived and held there through
# the dwell. Past this long it is stuck, not dwelling: the schedule expected it
# to have left, riders are waiting, and the clock is the right measure again.
HOLD_CAP_S = 300

# an added trip with no scheduled slot within this of its stop stays unmatched
MATCH_WINDOW_S = 3600
# within this of the nearest slot, prefer the trip with the most stops: a
# short-turn's timetable ends early and the train would lose its figure there
MATCH_PREFER_LONG_S = 600

MATCH_SQL = f"""
WITH cand AS (
    SELECT vp.trip_id, vp.start_date, vp.route_id, vp.direction_id, vp.stop_id,
           vp.current_stop_sequence AS feed_seq, vp.ts
    FROM vehicle_position vp
    WHERE vp.id = ANY($1::bigint[])
      AND vp.trip_id LIKE 'ADDED%'
      AND vp.start_date IS NOT NULL AND vp.route_id IS NOT NULL
      AND vp.direction_id IS NOT NULL AND vp.stop_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM added_trip_match m
                      WHERE m.trip_id = vp.trip_id AND m.start_date = vp.start_date)
),
-- match on when the vehicle reaches the stop: the feed's prediction for it
-- where we have one, otherwise now
target AS (
    SELECT DISTINCT ON (c.trip_id, c.start_date)
           c.*, COALESCE(tu.arrival_time, tu.departure_time, c.ts) AS at_stop
    FROM cand c
    LEFT JOIN LATERAL (
        SELECT tu.arrival_time, tu.departure_time
        FROM trip_update tu
        WHERE tu.trip_id = c.trip_id AND tu.stop_sequence = c.feed_seq AND tu.ts <= c.ts
        ORDER BY tu.ts DESC
        LIMIT 1
    ) tu ON true
    ORDER BY c.trip_id, c.start_date, c.ts
),
-- candidates come from trip_stop_offset rather than stop_time: only trips
-- with a shape can be placed, and it is the table the estimator reads
scored AS (
    SELECT t.trip_id, t.start_date, t.stop_id, t.ts,
           o.trip_id AS scheduled_trip_id,
           round(extract(epoch FROM t.at_stop
                 - gtfs_ts(t.start_date, COALESCE(o.arrival_s, o.departure_s), $2::text)))::int
               AS offset_s,
           (SELECT count(*) FROM trip_stop_offset n WHERE n.trip_id = o.trip_id) AS stops
    FROM target t
    JOIN trip_stop_offset o ON o.stop_id = t.stop_id
    JOIN trip tr ON tr.trip_id = o.trip_id
                AND tr.route_id = t.route_id AND tr.direction_id = t.direction_id
    WHERE COALESCE(o.arrival_s, o.departure_s) IS NOT NULL
)
INSERT INTO added_trip_match (trip_id, start_date, scheduled_trip_id, ts, matched_stop_id, offset_s)
SELECT DISTINCT ON (trip_id, start_date)
       trip_id, start_date, scheduled_trip_id, ts, stop_id, offset_s
FROM scored
WHERE abs(offset_s) <= {MATCH_WINDOW_S}
ORDER BY trip_id, start_date, abs(offset_s) > {MATCH_PREFER_LONG_S}, stops DESC, abs(offset_s)
ON CONFLICT DO NOTHING
"""


COMPUTE_SQL = f"""
WITH obs AS (
    SELECT vp.id, vp.vehicle_id, vp.trip_id, vp.route_id, vp.direction_id,
           vp.ts, vp.start_date, vp.current_status,
           vp.current_stop_sequence AS feed_seq,
           -- the timetable to read: the vehicle's own trip, or for an added
           -- trip the scheduled one it was matched to, through the stop id
           COALESCE(m.scheduled_trip_id, vp.trip_id)            AS sched_trip_id,
           COALESCE(ms.stop_sequence, vp.current_stop_sequence) AS seq,
           vp.geom_p
    FROM vehicle_position vp
    LEFT JOIN added_trip_match m
           ON m.trip_id = vp.trip_id AND m.start_date = vp.start_date
    LEFT JOIN trip_stop_offset ms
           ON ms.trip_id = m.scheduled_trip_id AND ms.stop_id = vp.stop_id
    WHERE vp.id = ANY($1::bigint[])
      AND vp.trip_id IS NOT NULL
      AND vp.start_date IS NOT NULL
      AND vp.current_stop_sequence IS NOT NULL
      AND (m.trip_id IS NULL OR ms.stop_sequence IS NOT NULL)
),
placed AS (
    SELECT o.*,
           t.route_id AS trip_route_id,
           ST_LineLocatePoint(sh.geom_p, o.geom_p) AS frac,
           ST_Distance(sh.geom_p, o.geom_p)        AS snap_error_m
    FROM obs o
    JOIN trip  t  ON t.trip_id  = o.sched_trip_id
    JOIN shape sh ON sh.shape_id = t.shape_id
),
-- the stop we're heading for, plus the one behind us: the current leg
bracketed AS (
    SELECT p.*,
           cur.arrival_s    AS cur_arrival_s,
           cur.departure_s  AS cur_departure_s,
           cur.frac         AS cur_frac,
           prev.departure_s AS prev_departure_s,
           prev.frac        AS prev_frac,
           prev.stop_sequence AS prev_seq,
           arr.arrived_ts
    FROM placed p
    JOIN trip_stop_offset cur
      ON cur.trip_id = p.sched_trip_id AND cur.stop_sequence = p.seq
    LEFT JOIN LATERAL (
        SELECT o2.departure_s, o2.frac, o2.stop_sequence
        FROM trip_stop_offset o2
        WHERE o2.trip_id = p.sched_trip_id AND o2.stop_sequence < p.seq
        ORDER BY o2.stop_sequence DESC
        LIMIT 1
    ) prev ON true
    -- when the vehicle first reported itself stopped here. The MBTA schedules
    -- arrival = departure at nearly every stop, so measuring a dwelling vehicle
    -- against the clock reads one second later per second it sits; measure it
    -- at the arrival event instead and hold that through the dwell
    LEFT JOIN LATERAL (
        SELECT min(vp2.ts) AS arrived_ts
        FROM vehicle_position vp2
        WHERE vp2.vehicle_id = p.vehicle_id
          AND vp2.trip_id = p.trip_id
          AND vp2.start_date = p.start_date
          AND vp2.current_stop_sequence = p.feed_seq
          AND vp2.current_status = 'STOPPED_AT'
          AND vp2.ts BETWEEN p.ts - interval '3 hours' AND p.ts
    ) arr ON p.current_status = 'STOPPED_AT'
),
positioned AS (
    SELECT b.*,
           CASE
               WHEN b.prev_frac IS NULL OR b.cur_frac IS NULL THEN NULL
               WHEN b.cur_frac - b.prev_frac <= 1e-9 THEN NULL
               ELSE (b.frac - b.prev_frac) / (b.cur_frac - b.prev_frac)
           END AS raw_ratio
    FROM bracketed b
),
resolved AS (
    SELECT p.*,
           CASE
               -- nothing before it in the trip, so it's sitting at the origin
               WHEN p.current_status = 'STOPPED_AT' AND p.prev_seq IS NULL
                    AND COALESCE(p.cur_departure_s, p.cur_arrival_s) IS NOT NULL
                   THEN 'layover'
               WHEN p.current_status = 'STOPPED_AT' AND p.cur_arrival_s IS NOT NULL
                   THEN 'stopped_at'
               WHEN p.raw_ratio IS NOT NULL AND p.prev_departure_s IS NOT NULL
                    AND p.cur_arrival_s IS NOT NULL
                   THEN 'interpolated'
               -- a preceding stop exists but the leg's fractions run backwards
               -- (loops, out-and-backs); scoring that against the next stop's
               -- arrival would read as late by the whole leg, so drop it
               WHEN p.prev_seq IS NULL AND p.cur_arrival_s IS NOT NULL
                   THEN 'first_stop'
               ELSE NULL
           END AS method,
           -- outside [0,1] means it drifted off the leg; raw_ratio is kept so
           -- the confidence check below can see that happened
           LEAST(GREATEST(COALESCE(p.raw_ratio, 0), 0), 1) AS ratio
    FROM positioned p
),
scheduled AS (
    SELECT r.*,
           CASE r.method
               WHEN 'layover'      THEN COALESCE(r.cur_departure_s,
                                                 r.cur_arrival_s)::double precision
               WHEN 'stopped_at'   THEN r.cur_arrival_s::double precision
               WHEN 'interpolated' THEN r.prev_departure_s
                                        + r.ratio * (r.cur_arrival_s - r.prev_departure_s)
               WHEN 'first_stop'   THEN r.cur_arrival_s::double precision
           END AS scheduled_s
    FROM resolved r
    WHERE r.method IS NOT NULL
),
final AS (
    SELECT s.id, s.vehicle_id, s.trip_id,
           COALESCE(s.route_id, s.trip_route_id) AS route_id,
           s.direction_id, s.ts, s.frac, s.snap_error_m, s.method,
           gtfs_ts(s.start_date, round(s.scheduled_s)::integer, $2::text) AS scheduled_time,
           CASE
               -- waiting at the origin for your departure isn't early
               WHEN s.method IN ('layover', 'first_stop')
                   THEN GREATEST(0, round(extract(epoch FROM
                        s.ts - gtfs_ts(s.start_date, round(s.scheduled_s)::integer, $2::text))))
               -- the deviation on arrival, held for the dwell, until the
               -- dwell has gone on long enough to be a breakdown
               WHEN s.method = 'stopped_at'
                   THEN round(extract(epoch FROM
                        CASE WHEN s.arrived_ts IS NULL
                               OR s.ts - s.arrived_ts > interval '{HOLD_CAP_S} seconds'
                             THEN s.ts ELSE s.arrived_ts END
                        - gtfs_ts(s.start_date, round(s.scheduled_s)::integer, $2::text)))
               ELSE round(extract(epoch FROM
                        s.ts - gtfs_ts(s.start_date, round(s.scheduled_s)::integer, $2::text)))
           END::integer AS computed_delay_s,
           s.feed_seq,
           s.raw_ratio
    FROM scheduled s
),
with_feed AS (
    SELECT f.*, tu.feed_delay_s
    FROM final f
    -- nearest the observation, not newest: newest makes backfill compare an
    -- early-trip position against a prediction from the end of that trip.
    -- A layover is measured against its departure, so compare it with the
    -- predicted departure; everything else is against an arrival
    LEFT JOIN LATERAL (
        SELECT CASE WHEN f.method = 'layover'
                    THEN COALESCE(tu.departure_delay_s, tu.delay_s)
                    ELSE COALESCE(tu.delay_s, tu.departure_delay_s) END AS feed_delay_s
        FROM trip_update tu
        WHERE tu.trip_id = f.trip_id
          AND tu.stop_sequence = f.feed_seq
          AND COALESCE(tu.delay_s, tu.departure_delay_s) IS NOT NULL
          AND tu.ts BETWEEN f.ts - interval '5 minutes'
                        AND f.ts + interval '5 minutes'
        ORDER BY abs(extract(epoch FROM tu.ts - f.ts))
        LIMIT 1
    ) tu ON true
)
INSERT INTO delay_observation
    (vehicle_id, trip_id, route_id, direction_id, ts, frac, snap_error_m,
     scheduled_time, computed_delay_s, feed_delay_s, divergence_s,
     method, confidence)
SELECT w.vehicle_id, w.trip_id, w.route_id, w.direction_id, w.ts, w.frac,
       w.snap_error_m, w.scheduled_time, w.computed_delay_s, w.feed_delay_s,
       CASE WHEN w.feed_delay_s IS NULL THEN NULL
            ELSE w.computed_delay_s - w.feed_delay_s END,
       w.method,
       CASE
           WHEN abs(w.computed_delay_s) > {IMPLAUSIBLE_DELAY_S} THEN 'low'
           WHEN w.snap_error_m > {MAX_SNAP_ERROR_M}             THEN 'low'
           WHEN w.method IN ('stopped_at', 'layover')           THEN 'high'
           WHEN w.method = 'first_stop'                         THEN 'medium'
           WHEN w.raw_ratio < 0 OR w.raw_ratio > 1              THEN 'medium'
           ELSE 'high'
       END
FROM with_feed w
ON CONFLICT (vehicle_id, ts) DO NOTHING
RETURNING 1
"""


async def compute(conn: asyncpg.Connection, position_ids: list[int]) -> int:
    if not position_ids:
        return 0
    await conn.execute(MATCH_SQL, position_ids, AGENCY_TZ)
    rows = await conn.fetch(COMPUTE_SQL, position_ids, AGENCY_TZ)
    return len(rows)


async def backfill(conn: asyncpg.Connection, hours: int | None = None) -> int:
    """Recompute recent delays. The raw positions are already stored, so you
    can change the estimator and rebuild without waiting for new data.

    One transaction, delete first: a poll that lands after the delete is
    either wholly visible to the id snapshot (and its own observation wins
    on conflict) or not visible at all, so nothing is lost either way.
    """
    hours = BACKFILL_HOURS if hours is None else hours
    async with conn.transaction():
        await conn.execute(
            "DELETE FROM delay_observation WHERE ts > now() - ($1 || ' hours')::interval",
            str(hours),
        )
        ids = [
            r["id"]
            for r in await conn.fetch(
                "SELECT id FROM vehicle_position WHERE ts > now() - ($1 || ' hours')::interval",
                str(hours),
            )
        ]
        total = 0
        for i in range(0, len(ids), 5000):
            total += await compute(conn, ids[i : i + 5000])
    return total
