import pathlib

import asyncpg
import pytest

SCHEMA = pathlib.Path(__file__).resolve().parents[1] / "app" / "schema.sql"
ADMIN_URL = "postgresql://localhost:5432/postgres"
TEST_URL = "postgresql://localhost:5432/tracker_test"

# A straight east-west line at lat 42.35, three stops: start, midpoint, end.
# Schedule: 05:00:00 depart, 05:05:00 arrive mid (05:06:00 depart), 05:10:00 end.
STATIC_SQL = """
INSERT INTO route VALUES ('R1', '1', 'Test Route', 3, NULL, NULL, 1);

INSERT INTO shape
SELECT 'S1', g, ST_Transform(g, 26986), ST_Length(ST_Transform(g, 26986))
FROM (SELECT ST_SetSRID(ST_MakeLine(
    ST_MakePoint(-71.10, 42.35), ST_MakePoint(-71.08, 42.35)), 4326) AS g) s;

INSERT INTO trip VALUES ('T1', 'R1', 'SVC', 'S1', 0, 'Test');

INSERT INTO trip_stop_offset
SELECT 'S1', 'T1', v.seq, v.stop,
       ST_LineLocatePoint(sh.geom_p,
           ST_Transform(ST_SetSRID(ST_MakePoint(v.lon, 42.35), 4326), 26986)),
       0, 0, v.arr, v.dep, true
FROM shape sh,
     (VALUES (1, 'ST1', -71.10, 18000, 18000),
             (2, 'ST2', -71.09, 18300, 18360),
             (3, 'ST3', -71.08, 18600, 18600)) v(seq, stop, lon, arr, dep)
WHERE sh.shape_id = 'S1';
"""


@pytest.fixture(scope="session")
async def db():
    admin = await asyncpg.connect(ADMIN_URL)
    await admin.execute("DROP DATABASE IF EXISTS tracker_test WITH (FORCE)")
    await admin.execute("CREATE DATABASE tracker_test")
    await admin.close()

    conn = await asyncpg.connect(TEST_URL)
    await conn.execute(SCHEMA.read_text())
    await conn.execute(STATIC_SQL)
    yield conn
    await conn.close()


@pytest.fixture
async def conn(db):
    await db.execute(
        "TRUNCATE vehicle_position, trip_update, delay_observation RESTART IDENTITY"
    )
    return db
