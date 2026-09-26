"""Score both arrival estimates against the arrival that followed.

Two estimates exist for every upcoming stop: the MBTA's predicted arrival, and
the one implied by where the vehicle is against its timetable (delay.py).
Neither can judge the other. The vehicle's first STOPPED_AT report at the stop
can judge both.

Every prediction for every stop is too much to store, so the ingest keeps a
prediction only at the moments its countdown reads one of HORIZONS_S: "when
the sign said five minutes". The hourly pass then takes the arrivals that have
settled, pairs each sample with the position-derived figure the estimator held
at the same moment, and writes one row per arrival.

    python -m app.services.scoring --hours 20   # catch up by hand
"""

import argparse
import asyncio
import datetime as dt
import logging
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg

from .. import db
from ..config import (
    AGENCY_TZ,
    SAMPLE_RETENTION_H,
    SCORE_INTERVAL_S,
    SCORE_LOOKBACK_H,
    SCORE_RETENTION_DAYS,
    SCORE_SETTLE_S,
)

log = logging.getLogger("tracker.scoring")

# countdown readings to sample, in seconds; the arrival_score columns mirror it
HORIZONS_S = (60, 120, 300, 600, 900, 1200)
# predictions are re-issued every poll, ~15s apart, so the nearest one to a
# horizon lands within this
SAMPLE_TOLERANCE_S = 30
# the position-derived figure paired with a sample must be from within this
MATCH_WINDOW_S = 45


def horizon_for(lead_s: int) -> int | None:
    """The horizon this countdown reading samples, or None."""
    for h in HORIZONS_S:
        if abs(lead_s - h) <= SAMPLE_TOLERANCE_S:
            return h
    return None


async def insert_samples(conn: asyncpg.Connection, samples: list[tuple[Any, ...]]) -> int:
    """(trip_id, start_date, stop_sequence, horizon_s, ts, predicted_time, lead_s)
    rows, one per key. A later reading closer to its horizon replaces the
    stored one."""
    if not samples:
        return 0
    cols = list(zip(*samples, strict=True))
    status = await conn.execute(
        """
        INSERT INTO prediction_sample
            (trip_id, start_date, stop_sequence, horizon_s, ts, predicted_time, lead_s)
        SELECT * FROM unnest($1::text[], $2::date[], $3::integer[], $4::integer[],
                             $5::timestamptz[], $6::timestamptz[], $7::integer[])
        ON CONFLICT (trip_id, start_date, stop_sequence, horizon_s) DO UPDATE
            SET ts = excluded.ts,
                predicted_time = excluded.predicted_time,
                lead_s = excluded.lead_s
            WHERE abs(excluded.lead_s - excluded.horizon_s)
                < abs(prediction_sample.lead_s - prediction_sample.horizon_s)
        """,
        *cols,
    )
    return int(status.split()[-1])


_SCORE_COLS = ", ".join(f"feed_{h}, position_{h}" for h in HORIZONS_S)
_SCORE_PIVOT = ",\n       ".join(
    f"max(smp.feed_error_s) FILTER (WHERE smp.horizon_s = {h}),\n"
    f"       max(smp.position_error_s) FILTER (WHERE smp.horizon_s = {h})"
    for h in HORIZONS_S
)

SCORE_SQL = f"""
WITH arrivals AS (
    -- first STOPPED_AT report per vehicle, trip and stop, for arrivals inside
    -- the window; the earlier lookback catches a dwell that began before it
    SELECT vp.vehicle_id, vp.trip_id, vp.start_date,
           vp.current_stop_sequence AS seq, min(vp.ts) AS arrived_at
    FROM vehicle_position vp
    WHERE vp.current_status = 'STOPPED_AT'
      AND vp.trip_id IS NOT NULL AND vp.start_date IS NOT NULL
      AND vp.current_stop_sequence IS NOT NULL
      AND vp.ts >= $1::timestamptz - interval '3 hours' AND vp.ts < $2::timestamptz
    GROUP BY 1, 2, 3, 4
    HAVING min(vp.ts) >= $1::timestamptz
),
fresh AS (
    SELECT a.* FROM arrivals a
    WHERE NOT EXISTS (
        SELECT 1 FROM arrival_score x
        WHERE x.vehicle_id = a.vehicle_id AND x.trip_id = a.trip_id
          AND x.start_date = a.start_date AND x.stop_sequence = a.seq)
),
-- seen on the way in: an earlier report on the same trip short of this stop.
-- Rules out the origin layover and a vehicle first seen already stopped
approached AS (
    SELECT f.*, vp.route_id, vp.direction_id, vp.stop_id
    FROM fresh f
    JOIN vehicle_position vp ON vp.vehicle_id = f.vehicle_id AND vp.ts = f.arrived_at
    WHERE EXISTS (
        SELECT 1 FROM vehicle_position p
        WHERE p.trip_id = f.trip_id AND p.vehicle_id = f.vehicle_id
          AND p.start_date = f.start_date
          AND p.ts < f.arrived_at AND p.ts >= f.arrived_at - interval '3 hours'
          AND (p.current_stop_sequence < f.seq
               OR (p.current_stop_sequence = f.seq AND p.current_status <> 'STOPPED_AT')))
),
scheduled AS (
    SELECT a.vehicle_id, a.trip_id, a.start_date, a.seq, a.arrived_at, a.direction_id,
           COALESCE(a.route_id, t.route_id) AS route_id,
           COALESCE(a.stop_id, o.stop_id) AS stop_id,
           gtfs_ts(a.start_date, o.arrival_s, $3::text) AS scheduled_time
    FROM approached a
    JOIN trip t ON t.trip_id = a.trip_id
    JOIN trip_stop_offset o ON o.trip_id = a.trip_id AND o.stop_sequence = a.seq
    WHERE o.arrival_s IS NOT NULL
      -- the origin is a departure, not an arrival
      AND a.seq > (SELECT min(stop_sequence) FROM trip_stop_offset WHERE trip_id = a.trip_id)
),
-- each sampled reading, with the estimator's figure from the same moment
samples AS (
    SELECT s.vehicle_id, s.trip_id, s.start_date, s.seq, ps.horizon_s,
           round(extract(epoch FROM ps.predicted_time - s.arrived_at))::int AS feed_error_s,
           CASE WHEN d.computed_delay_s IS NULL THEN NULL
                ELSE round(extract(epoch FROM s.scheduled_time - s.arrived_at))::int
                     + d.computed_delay_s END AS position_error_s
    FROM scheduled s
    JOIN prediction_sample ps
      ON ps.trip_id = s.trip_id AND ps.start_date = s.start_date
     AND ps.stop_sequence = s.seq AND ps.ts < s.arrived_at
    LEFT JOIN LATERAL (
        SELECT d.computed_delay_s
        FROM delay_observation d
        WHERE d.vehicle_id = s.vehicle_id AND d.trip_id = s.trip_id
          AND d.confidence IN ('high', 'medium')
          AND d.ts BETWEEN ps.ts - interval '{MATCH_WINDOW_S} seconds'
                       AND ps.ts + interval '{MATCH_WINDOW_S} seconds'
        ORDER BY abs(extract(epoch FROM d.ts - ps.ts))
        LIMIT 1
    ) d ON true
)
INSERT INTO arrival_score
    (vehicle_id, trip_id, route_id, direction_id, start_date, stop_sequence,
     stop_id, scheduled_time, arrived_at, {_SCORE_COLS})
SELECT s.vehicle_id, s.trip_id, s.route_id, s.direction_id, s.start_date, s.seq,
       s.stop_id, s.scheduled_time, s.arrived_at,
       {_SCORE_PIVOT}
FROM scheduled s
LEFT JOIN samples smp
       ON smp.vehicle_id = s.vehicle_id AND smp.trip_id = s.trip_id
      AND smp.start_date = s.start_date AND smp.seq = s.seq
GROUP BY s.vehicle_id, s.trip_id, s.route_id, s.direction_id, s.start_date, s.seq,
         s.stop_id, s.scheduled_time, s.arrived_at
ON CONFLICT (vehicle_id, trip_id, start_date, stop_sequence) DO NOTHING
RETURNING 1
"""


async def score(conn: asyncpg.Connection, since: dt.datetime, until: dt.datetime) -> int:
    """Write a row for every not-yet-scored arrival in [since, until)."""
    rows = await conn.fetch(SCORE_SQL, since, until, AGENCY_TZ)
    return len(rows)


_AGG_COLS = [
    "arrivals",
    "feed_n", "feed_mean_s", "feed_mean_abs_s", "feed_within_60", "feed_within_120",
    "position_n", "position_mean_s", "position_mean_abs_s",
    "position_within_60", "position_within_120",
]
_AGG_VALUES = ", ".join(f"({h}, a.feed_{h}, a.position_{h})" for h in HORIZONS_S)

AGGREGATE_SQL = f"""
INSERT INTO arrival_score_daily (day, route_id, horizon_s, hour, {", ".join(_AGG_COLS)})
SELECT $1::date, a.route_id, h.horizon_s,
       extract(hour FROM a.arrived_at AT TIME ZONE $2::text)::smallint,
       count(*),
       count(h.feed), round(avg(h.feed))::int, round(avg(abs(h.feed)))::int,
       count(*) FILTER (WHERE abs(h.feed) <= 60),
       count(*) FILTER (WHERE abs(h.feed) <= 120),
       count(h.position), round(avg(h.position))::int, round(avg(abs(h.position)))::int,
       count(*) FILTER (WHERE abs(h.position) <= 60),
       count(*) FILTER (WHERE abs(h.position) <= 120)
FROM arrival_score a
CROSS JOIN LATERAL (VALUES {_AGG_VALUES}) AS h(horizon_s, feed, position)
WHERE a.arrived_at >= ($1::date::timestamp AT TIME ZONE $2::text)
  AND a.arrived_at <  (($1::date + 1)::timestamp AT TIME ZONE $2::text)
GROUP BY 2, 3, 4
ON CONFLICT (day, route_id, horizon_s, hour) DO UPDATE SET
    {", ".join(f"{c} = excluded.{c}" for c in _AGG_COLS)}
"""


async def aggregate(conn: asyncpg.Connection, day: dt.date) -> int:
    """Rebuild one service day's rollup from arrival_score."""
    status = await conn.execute(AGGREGATE_SQL, day, AGENCY_TZ)
    return int(status.split()[-1])


async def prune(conn: asyncpg.Connection) -> dict[str, int]:
    samples = await conn.execute(
        "DELETE FROM prediction_sample WHERE ts < now() - ($1 || ' hours')::interval",
        str(SAMPLE_RETENTION_H),
    )
    scores = await conn.execute(
        "DELETE FROM arrival_score WHERE arrived_at < now() - ($1 || ' days')::interval",
        str(SCORE_RETENTION_DAYS),
    )
    return {
        "prediction_sample": int(samples.split()[-1]),
        "arrival_score": int(scores.split()[-1]),
    }


def service_days(since: dt.datetime, until: dt.datetime) -> list[dt.date]:
    tz = ZoneInfo(AGENCY_TZ)
    first = since.astimezone(tz).date()
    last = (until - dt.timedelta(seconds=1)).astimezone(tz).date()
    return sorted({first, last})


async def run_once(
    conn: asyncpg.Connection,
    *,
    lookback_h: float = SCORE_LOOKBACK_H,
    settle_s: int = SCORE_SETTLE_S,
) -> dict[str, Any]:
    """Score what has settled, roll up the days it touched, prune."""
    until = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=settle_s)
    since = until - dt.timedelta(hours=lookback_h)
    # an arrival is only scorable once every reading for it could have been
    # sampled, so nothing from before sampling began plus the longest horizon.
    # In steady state the oldest sample is a day old and this changes nothing
    floor = await conn.fetchval(
        "SELECT min(ts) + ($1 || ' seconds')::interval FROM prediction_sample",
        str(max(HORIZONS_S)),
    )
    if floor is None:
        return {"scored": 0, "days": [], "pruned": await prune(conn)}
    since = max(since, floor)
    scored = await score(conn, since, until) if since < until else 0
    days = service_days(since, until)
    for day in days:
        await aggregate(conn, day)
    pruned = await prune(conn)
    return {"scored": scored, "days": [d.isoformat() for d in days], "pruned": pruned}


async def run_forever() -> None:
    while True:
        try:
            async with db.pool().acquire() as conn:
                r = await run_once(conn)
            log.info(
                "scored %d arrivals, rolled up %s, pruned %d samples",
                r["scored"], ", ".join(r["days"]), r["pruned"]["prediction_sample"],
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("scoring failed: %s: %s", type(exc).__name__, exc)
        await asyncio.sleep(SCORE_INTERVAL_S)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Score settled arrivals against both estimates")
    ap.add_argument("--hours", type=float, default=SCORE_LOOKBACK_H,
                    help="how far back to look (positions are kept 48h, samples 24h)")
    args = ap.parse_args()

    async def _main() -> None:
        pool = await db.connect()
        try:
            async with pool.acquire() as conn:
                print(await run_once(conn, lookback_h=args.hours))
        finally:
            await db.close()

    asyncio.run(_main())
