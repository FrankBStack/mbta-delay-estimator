"""Scoring both arrival estimates against the arrival that followed."""

from app.services import realtime, scoring
from tests.test_delay import SERVICE_DATE, at, observe
from tests.test_realtime import updates_msg


def test_horizon_for_picks_the_nearest_reading():
    assert scoring.horizon_for(300) == 300
    assert scoring.horizon_for(275) == 300
    assert scoring.horizon_for(1230) == 1200
    assert scoring.horizon_for(200) is None
    assert scoring.horizon_for(-5) is None


async def sample(conn, seq, horizon, ts, predicted):
    lead = round((predicted - ts).total_seconds())
    await scoring.insert_samples(
        conn, [("T1", SERVICE_DATE, seq, horizon, ts, predicted, lead)]
    )


async def test_ingest_samples_readings_at_the_horizons(conn):
    # header at 18240; predicted arrivals 18360, 18420, 18480: leads 120, 180, 240
    await realtime.ingest_trip_updates(conn, updates_msg("T1", [1, 2, 3]))
    rows = await conn.fetch("SELECT stop_sequence, horizon_s, lead_s FROM prediction_sample")
    assert [tuple(r) for r in rows] == [(1, 120, 120)]


async def test_a_closer_reading_replaces_the_sample(conn):
    await sample(conn, 2, 300, at(18000), at(18325))  # lead 325
    await sample(conn, 2, 300, at(18015), at(18325))  # lead 310, closer
    await sample(conn, 2, 300, at(17970), at(18325))  # lead 355, further: ignored
    row = await conn.fetchrow("SELECT ts, lead_s FROM prediction_sample")
    assert (row["ts"], row["lead_s"]) == (at(18015), 310)


async def test_scores_both_estimates_against_the_arrival(conn):
    # halfway to ST2 at 05:02:30, exactly on schedule: position implies 05:05:00
    await observe(conn, at(18150), -71.095, seq=2, status="IN_TRANSIT_TO")
    # the feed at the same moment said two minutes: 05:04:30
    await sample(conn, 2, 120, at(18150), at(18270))
    # it arrived at 05:06:00
    await observe(conn, at(18360), -71.09, seq=2, status="STOPPED_AT")

    assert await scoring.score(conn, at(18000), at(19000)) == 1
    row = await conn.fetchrow("SELECT * FROM arrival_score")
    assert row["stop_sequence"] == 2
    assert row["arrived_at"] == at(18360)
    assert row["scheduled_time"] == at(18300)
    assert row["feed_120"] == -90
    assert row["position_120"] == -60
    assert row["feed_300"] is None and row["position_300"] is None

    # a second pass finds nothing new
    assert await scoring.score(conn, at(18000), at(19000)) == 0

    await scoring.aggregate(conn, SERVICE_DATE)
    day = await conn.fetchrow("SELECT * FROM arrival_score_daily WHERE horizon_s = 120")
    assert (day["route_id"], day["hour"], day["arrivals"]) == ("R1", 5, 1)
    assert (day["feed_n"], day["feed_mean_s"]) == (1, -90)
    assert (day["feed_within_60"], day["feed_within_120"]) == (0, 1)
    assert (day["position_n"], day["position_mean_abs_s"], day["position_within_60"]) == (1, 60, 1)
    # the unsampled horizons roll up as arrivals with nothing to score
    other = await conn.fetchrow(
        "SELECT feed_n, arrivals FROM arrival_score_daily WHERE horizon_s = 600"
    )
    assert (other["feed_n"], other["arrivals"]) == (0, 1)


async def test_origin_and_unseen_approaches_are_not_arrivals(conn):
    # sitting at the origin is a layover, not an arrival
    await observe(conn, at(17900), -71.10, seq=1, status="STOPPED_AT")
    # first seen already stopped at ST3, never seen approaching it
    await observe(conn, at(18700), -71.08, seq=3, status="STOPPED_AT", vehicle="v2")
    assert await scoring.score(conn, at(17000), at(19000)) == 0


async def test_a_dwell_that_began_before_the_window_is_not_rescored(conn):
    await observe(conn, at(18150), -71.095, seq=2, status="IN_TRANSIT_TO")
    await observe(conn, at(18360), -71.09, seq=2, status="STOPPED_AT")
    await observe(conn, at(18400), -71.09, seq=2, status="STOPPED_AT")
    # a window that opens after the arrival sees the later report but must not
    # take it for the arrival
    assert await scoring.score(conn, at(18380), at(19000)) == 0
    assert await scoring.score(conn, at(18000), at(19000)) == 1
