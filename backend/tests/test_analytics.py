"""What the aggregates leave out."""

from datetime import UTC, datetime

from app import db
from app.routers import analytics


async def observation(conn, vehicle, *, method, delay_s, confidence="high"):
    now = datetime.now(UTC)
    await conn.execute(
        """
        INSERT INTO delay_observation
            (vehicle_id, trip_id, route_id, direction_id, ts, frac, snap_error_m,
             scheduled_time, computed_delay_s, feed_delay_s, divergence_s,
             method, confidence)
        VALUES ($1, 'T1', 'R1', 0, $2, 0.5, 0, $2, $3, $3, 0, $4, $5)
        """,
        vehicle, now, delay_s, method, confidence,
    )


async def test_vehicles_ahead_of_their_origin_are_left_out(conn, monkeypatch):
    monkeypatch.setattr(db, "_pool", conn)
    await observation(conn, "waiting", method="layover", delay_s=0)
    await observation(conn, "heading", method="first_stop", delay_s=0)
    await observation(conn, "late-leaving", method="layover", delay_s=200)
    await observation(conn, "moving", method="interpolated", delay_s=100)
    await observation(conn, "off-route", method="interpolated", delay_s=900, confidence="low")

    out = await analytics._delay_by_route(60, None, 1, False)
    assert [r["observations"] for r in out["routes"]] == [2]
    assert out["routes"][0]["mean_computed_s"] == 150

    div = await analytics._divergence(60, False)
    assert div["observations"] == 2
