"""A feed load swaps in a complete set of static tables, or changes nothing."""

import zipfile

import pytest

from app import gtfs_static
from tests.conftest import STATIC_SCHEMA, STATIC_SQL

# the same east-west line as conftest, with the last stop after midnight
FILES = {
    "routes.txt": (
        "route_id,route_short_name,route_long_name,route_type,route_color,"
        "route_text_color,route_sort_order\nZ1,9,Zip Route,3,,,1\n"
    ),
    "stops.txt": (
        "stop_id,stop_name,parent_station,stop_lat,stop_lon\n"
        "ZS1,A,,42.35,-71.10\nZS2,B,,42.35,-71.09\nZS3,C,,42.35,-71.08\n"
    ),
    "shapes.txt": (
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
        "ZSH,42.35,-71.10,1\nZSH,42.35,-71.08,2\n"
    ),
    "trips.txt": (
        "trip_id,route_id,service_id,shape_id,direction_id,trip_headsign\n"
        "ZT1,Z1,ZSVC,ZSH,0,Zip\n"
    ),
    "stop_times.txt": (
        "trip_id,stop_sequence,stop_id,arrival_time,departure_time\n"
        "ZT1,1,ZS1,05:00:00,05:00:00\nZT1,2,ZS2,05:05:00,05:06:00\n"
        "ZT1,3,ZS3,25:10:00,25:10:00\n"
    ),
    "calendar.txt": (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
        "start_date,end_date\nZSVC,1,1,1,1,1,0,0,20260101,20261231\n"
    ),
    "feed_info.txt": (
        "feed_publisher_name,feed_publisher_url,feed_lang,feed_version,"
        "feed_start_date,feed_end_date\nTest,http://x,en,zip-1,20260101,20261231\n"
    ),
}


@pytest.fixture
def feed(tmp_path):
    path = tmp_path / "gtfs.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in FILES.items():
            zf.writestr(name, text)
    f = gtfs_static.Feed(path)
    yield f
    f.close()


async def staging_exists(conn):
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = $1)", gtfs_static.STAGING
    )


async def test_load_swaps_in_the_feed(conn, feed):
    try:
        await gtfs_static.load(conn, feed)

        assert await conn.fetchval("SELECT count(*) FROM trip") == 1
        rows = await conn.fetch(
            "SELECT stop_sequence, frac, arrival_s FROM trip_stop_offset ORDER BY 1"
        )
        assert [r["stop_sequence"] for r in rows] == [1, 2, 3]
        assert rows[1]["frac"] == pytest.approx(0.5, abs=0.01)
        assert rows[2]["arrival_s"] == 25 * 3600 + 600
        assert await conn.fetchval(
            "SELECT value FROM feed_meta WHERE key = 'feed_version'"
        ) == "zip-1"
        assert not await staging_exists(conn)
        assert gtfs_static.STAGING not in await conn.fetchval("SHOW search_path")
    finally:
        # put conftest's synthetic route back for the tests that follow
        await conn.execute(
            "DROP TABLE IF EXISTS " + ", ".join(gtfs_static.STATIC_TABLES) + " CASCADE"
        )
        await conn.execute(STATIC_SCHEMA.read_text())
        await conn.execute(STATIC_SQL)


async def test_a_failed_load_leaves_the_live_tables_alone(conn, feed, monkeypatch):
    async def broken(conn, feed):
        raise RuntimeError("stop_times.txt changed shape")

    monkeypatch.setattr(gtfs_static, "load_stop_times", broken)
    before = await conn.fetchval("SELECT count(*) FROM trip_stop_offset")

    with pytest.raises(RuntimeError):
        await gtfs_static.load(conn, feed)

    assert await conn.fetch("SELECT trip_id FROM trip ORDER BY 1") == [("T1",), ("T2",)]
    assert await conn.fetchval("SELECT count(*) FROM trip_stop_offset") == before
    assert not await staging_exists(conn)
