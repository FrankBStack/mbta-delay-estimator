"""Load a static GTFS zip into PostGIS.

    python -m app.gtfs_static              # download and load
    python -m app.gtfs_static --zip a.zip  # load one you already have
    python -m app.gtfs_static --keep       # keep the download around

Drops and rebuilds every table, then runs app.offsets. Slow and occasional;
the poller only ever reads these tables.
"""

import argparse
import asyncio
import csv
import datetime as dt
import io
import pathlib
import sys
import time
import zipfile

import httpx

from . import db, offsets
from .config import GTFS_STATIC_URL, PROJECTED_SRID

CACHE = pathlib.Path(__file__).resolve().parents[1] / ".cache"

# a long stop_desc will exceed the default limit
csv.field_size_limit(10_000_000)


def parse_gtfs_time(value):
    """'25:10:00' -> 90600. Times run past 24h for trips belonging to the
    previous service day, so this can't go through a time type."""
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = (int(p) for p in parts)
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


def parse_date(value):
    if not value or len(value) != 8:
        return None
    return dt.date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Feed:
    def __init__(self, path):
        self.zf = zipfile.ZipFile(path)
        self.names = set(self.zf.namelist())

    def has(self, name):
        return name in self.names

    def rows(self, name):
        if name not in self.names:
            return
        with self.zf.open(name) as raw:
            # utf-8-sig, because some agencies ship a BOM that would otherwise
            # end up glued to the first column name
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            yield from csv.DictReader(text)

    def close(self):
        self.zf.close()


async def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}")
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                async for chunk in resp.aiter_bytes(1 << 16):
                    fh.write(chunk)
    print(f"  {dest.stat().st_size/1e6:.1f} MB in {time.monotonic()-started:.1f}s")
    return dest


async def load_routes(conn, feed):
    rows = [
        (
            r["route_id"],
            r.get("route_short_name") or None,
            r.get("route_long_name") or None,
            _int(r.get("route_type", "")) or 3,
            r.get("route_color") or None,
            r.get("route_text_color") or None,
            _int(r.get("route_sort_order", "")),
        )
        for r in feed.rows("routes.txt")
    ]
    await conn.executemany(
        "INSERT INTO route (route_id, route_short_name, route_long_name,"
        " route_type, route_color, route_text_color, route_sort_order)"
        " VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING",
        rows,
    )
    return len(rows)


async def load_stops(conn, feed):
    records = []
    for r in feed.rows("stops.txt"):
        lat, lon = _float(r.get("stop_lat", "")), _float(r.get("stop_lon", ""))
        if lat is None or lon is None:
            # generic nodes / boarding areas have no coordinate
            continue
        records.append(
            (r["stop_id"], r.get("stop_name") or None,
             r.get("parent_station") or None, lat, lon)
        )

    await conn.execute(
        "CREATE TEMP TABLE stop_stage"
        " (stop_id text, stop_name text, parent_station text,"
        "  lat double precision, lon double precision) ON COMMIT DROP"
    )
    await conn.copy_records_to_table("stop_stage", records=records)
    await conn.execute(
        f"""
        INSERT INTO stop (stop_id, stop_name, parent_station, geom, geom_p)
        SELECT stop_id, stop_name, parent_station,
               ST_SetSRID(ST_MakePoint(lon, lat), 4326),
               ST_Transform(ST_SetSRID(ST_MakePoint(lon, lat), 4326), {PROJECTED_SRID})
        FROM stop_stage
        ON CONFLICT (stop_id) DO NOTHING
        """
    )
    return len(records)


async def load_shapes(conn, feed):
    """shapes.txt is a flat point list; stitch them into LineStrings."""
    by_shape = {}
    for r in feed.rows("shapes.txt"):
        lat, lon = _float(r.get("shape_pt_lat", "")), _float(r.get("shape_pt_lon", ""))
        seq = _int(r.get("shape_pt_sequence", ""))
        if lat is None or lon is None or seq is None:
            continue
        by_shape.setdefault(r["shape_id"], []).append((seq, lon, lat))

    records = []
    skipped = 0
    for shape_id, pts in by_shape.items():
        # sort explicitly; file order isn't guaranteed to match the sequence
        pts.sort(key=lambda p: p[0])
        coords = []
        for _, lon, lat in pts:
            if not coords or coords[-1] != (lon, lat):
                coords.append((lon, lat))
        if len(coords) < 2:
            skipped += 1
            continue
        wkt = "LINESTRING(" + ",".join(f"{lon} {lat}" for lon, lat in coords) + ")"
        records.append((shape_id, wkt))

    await conn.executemany(
        f"""
        INSERT INTO shape (shape_id, geom, geom_p, length_m)
        VALUES (
            $1,
            ST_GeomFromText($2, 4326),
            ST_Transform(ST_GeomFromText($2, 4326), {PROJECTED_SRID}),
            ST_Length(ST_Transform(ST_GeomFromText($2, 4326), {PROJECTED_SRID}))
        )
        ON CONFLICT (shape_id) DO NOTHING
        """,
        records,
    )
    if skipped:
        print(f"  skipped {skipped} shapes with < 2 distinct points")
    return len(records)


async def load_trips(conn, feed):
    known_shapes = {r["shape_id"] for r in await conn.fetch("SELECT shape_id FROM shape")}
    known_routes = {r["route_id"] for r in await conn.fetch("SELECT route_id FROM route")}
    records = []
    orphans = 0
    for r in feed.rows("trips.txt"):
        if r["route_id"] not in known_routes:
            orphans += 1
            continue
        shape_id = r.get("shape_id") or None
        if shape_id not in known_shapes:
            shape_id = None
        records.append(
            (r["trip_id"], r["route_id"], r["service_id"], shape_id,
             _int(r.get("direction_id", "")), r.get("trip_headsign") or None)
        )
    await conn.copy_records_to_table(
        "trip",
        records=records,
        columns=["trip_id", "route_id", "service_id", "shape_id",
                 "direction_id", "trip_headsign"],
    )
    if orphans:
        print(f"  skipped {orphans} trips on unknown routes")
    return len(records)


async def load_stop_times(conn, feed):
    """~2.2M rows for the MBTA, so stream it straight into COPY."""
    known_trips = {r["trip_id"] for r in await conn.fetch("SELECT trip_id FROM trip")}
    count = 0
    seen = set()

    def records():
        nonlocal count
        for r in feed.rows("stop_times.txt"):
            trip_id = r["trip_id"]
            if trip_id not in known_trips:
                continue
            seq = _int(r.get("stop_sequence", ""))
            if seq is None:
                continue
            # one duplicate key would abort the entire COPY
            key = (trip_id, seq)
            if key in seen:
                continue
            seen.add(key)
            count += 1
            yield (
                trip_id,
                seq,
                r["stop_id"],
                parse_gtfs_time(r.get("arrival_time", "")),
                parse_gtfs_time(r.get("departure_time", "")),
            )

    await conn.copy_records_to_table(
        "stop_time",
        records=records(),
        columns=["trip_id", "stop_sequence", "stop_id", "arrival_s", "departure_s"],
    )
    return count


async def load_calendar(conn, feed):
    cal = []
    for r in feed.rows("calendar.txt"):
        start = parse_date(r.get("start_date", ""))
        end = parse_date(r.get("end_date", ""))
        if start is None or end is None:
            continue
        cal.append(
            (r["service_id"], _int(r.get("monday", "")), _int(r.get("tuesday", "")),
             _int(r.get("wednesday", "")), _int(r.get("thursday", "")),
             _int(r.get("friday", "")), _int(r.get("saturday", "")),
             _int(r.get("sunday", "")), start, end)
        )
    await conn.executemany(
        "INSERT INTO calendar (service_id, monday, tuesday, wednesday, thursday,"
        " friday, saturday, sunday, start_date, end_date)"
        " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT DO NOTHING",
        cal,
    )

    dates = []
    for r in feed.rows("calendar_dates.txt"):
        d = parse_date(r.get("date", ""))
        if d is None:
            continue
        dates.append((r["service_id"], d, _int(r.get("exception_type", "")) or 1))
    await conn.executemany(
        "INSERT INTO calendar_date (service_id, date, exception_type)"
        " VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
        dates,
    )
    return len(cal), len(dates)


async def run(zip_path, keep):
    downloaded = False
    if zip_path is None:
        zip_path = CACHE / "gtfs.zip"
        if zip_path.exists():
            age_h = (time.time() - zip_path.stat().st_mtime) / 3600
            print(f"using cached {zip_path.name} ({age_h:.1f}h old)")
        else:
            await download(GTFS_STATIC_URL, zip_path)
            downloaded = True

    feed = Feed(zip_path)
    pool = await db.connect()
    try:
        async with pool.acquire() as conn:
            print("applying schema")
            await db.apply_schema(conn)

            async with conn.transaction():
                steps = [
                    ("routes", load_routes),
                    ("stops", load_stops),
                    ("shapes", load_shapes),
                    ("trips", load_trips),
                    ("stop_times", load_stop_times),
                ]
                for label, fn in steps:
                    started = time.monotonic()
                    n = await fn(conn, feed)
                    print(f"  {label:<12} {n:>9,}  ({time.monotonic()-started:.1f}s)")

                cal, dates = await load_calendar(conn, feed)
                print(f"  {'calendar':<12} {cal:>9,}  (+{dates:,} exceptions)")

                await conn.execute(
                    "INSERT INTO feed_meta (key, value) VALUES ('loaded_at', $1),"
                    " ('source', $2) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                    dt.datetime.now(dt.timezone.utc).isoformat(),
                    GTFS_STATIC_URL,
                )

            print("analyzing")
            for table in ("stop_time", "trip", "shape", "stop"):
                await conn.execute(f"ANALYZE {table}")

        await offsets.build()
    finally:
        feed.close()
        await db.close()
        if downloaded and not keep:
            zip_path.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description="Load static GTFS into PostGIS")
    ap.add_argument("--zip", type=pathlib.Path, help="load a local zip instead of downloading")
    ap.add_argument("--keep", action="store_true", help="keep the download in .cache")
    args = ap.parse_args()
    try:
        asyncio.run(run(args.zip, args.keep))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
