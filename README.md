# MBTA Delay Estimator

Real-time map of Boston transit vehicles. Delays are computed from each
vehicle's physical position against the published timetable, not read from the
agency feed.

The computed figure agrees with the MBTA's own predictions at r = 0.99 over a
weekday evening peak; see [Validation](#validation) below.

![Live map of Boston with vehicles colored by delay, alongside a panel comparing the position-derived figure to the MBTA's predictions](docs/screenshot.png)

GTFS-realtime protobuf feeds are polled into PostGIS by a FastAPI service; a
React + MapLibre frontend consumes the REST API. The MBTA's realtime feeds
require no API key.

**Stack:** Python 3.13, FastAPI, asyncpg, PostgreSQL 17 + PostGIS 3.6, React 18,
MapLibre GL, Vite.

## Deriving delay from position

Two fields are missing from the MBTA's data:

- `TripUpdates` has no `delay` field, only absolute predicted arrival times.
- `shape_dist_traveled` is empty across all 393,561 shape points, so there is no
  published measure of how far along a route a given stop sits.

The second is the bigger problem: without it there's no way to say "this
vehicle is between stops 7 and 8, 40% of the way along". `app.offsets` derives
it instead: `ST_LineLocatePoint` computes, for every distinct (shape, stop)
pair, the fraction along the route line at which that stop falls. That turns
the timetable into a mapping from position to time, so a live vehicle projected
onto its own shape can be compared with when the schedule expected a vehicle at
that point.

The work is keyed on (shape_id, stop_id) rather than (trip_id, stop_sequence).
87,656 trips share only 1,156 shapes, which reduces the geometry operations from
2.2M to roughly 24,000.

All distance computation runs in EPSG:26986 (NAD83 / Massachusetts Mainland, in
metres) rather than WGS84 degrees. At Boston's latitude a degree of longitude is
approximately 0.74 of a degree of latitude, so locating a point on a line in
unprojected coordinates biases the result east-west.

### Placing a vehicle on its route

`ST_LineLocatePoint` returns the first nearest point on the line, so on a loop
route a vehicle on its second pass resolves to a position near the start. This
affects 2.6% of MBTA trips, flagged at load time as `frac_monotonic = false`.
To handle it, the feed's `current_stop_sequence` picks which leg the vehicle is
on, and the geometry then locates it along that leg only.

Each observation records which method produced it:

| Method | Description |
|---|---|
| `interpolated` | In transit; scheduled time prorated along the shape between two stops |
| `stopped_at` | Stopped at a mid-route stop; that stop's scheduled time exactly |
| `layover` | Stopped at the trip's first stop; measured against scheduled departure, floored at zero |
| `first_stop` | Approaching the first stop, with no preceding stop to interpolate from |

Observations are marked low confidence where the vehicle sits more than 150m
from the shape it reports running, or where the result exceeds three hours —
typically indicating a mismatched service date. These are retained but excluded
from analytics by default.

Stop-to-shape snap error across the loaded feed: mean 7.0m, p95 11.9m.

## Validation

Since the MBTA publishes no delay field, its figure is derived for comparison
as predicted arrival minus scheduled arrival for the same trip and stop. Over a
weekday evening peak (87,461 paired observations) the two agree at correlation
0.9935, mean divergence +19s, 88.8% within 60s. They answer different
questions (ours is how late a vehicle is right now, theirs is how late it will
be on arrival), so they diverge most during long dwells and at peak service,
where correlation drops to 0.96 against 0.99 overnight.

[docs/validation.md](docs/validation.md) has the full breakdown: agreement by
service level and placement method, per-route examples, and a bug in
first-stop handling that the comparison caught.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/vehicles` | Live positions as GeoJSON, with both delay figures |
| `GET /api/vehicles/{id}/history` | Breadcrumb trail with per-point delay |
| `GET /api/routes` | Route list, optionally limited to those currently running |
| `GET /api/routes/{id}/shape` | Route geometry as GeoJSON |
| `GET /api/analytics/delay-by-route` | Mean delay per route, computed vs. feed |
| `GET /api/analytics/divergence` | Agreement statistics, broken down by method |
| `GET /api/analytics/timeline` | Both series bucketed over time |
| `GET /api/analytics/health` | Poller liveness and data volume |

Interactive documentation at `/docs`.

## Project layout

```
backend/app/
  schema.sql        tables, indexes, and the gtfs_ts() time helper
  gtfs_static.py    GTFS zip into PostGIS via streaming COPY
  offsets.py        ST_LineLocatePoint stop-position cache
  services/
    realtime.py     GTFS-realtime poller
    delay.py        the schedule join and comparison
  routers/          vehicles, routes, analytics
backend/tests/      the estimator run against a synthetic route in PostGIS
frontend/src/
  components/MapView.jsx            MapLibre map, diverging delay scale
  components/DelayByRouteChart.jsx  two-series comparison chart
  lib/delay.js                      color scale shared by map and legend
```

## Running locally

Requires PostgreSQL with PostGIS, Python 3.11+, and Node 18+.

```bash
brew install postgresql@17 postgis
brew services start postgresql@17
createdb tracker
psql -d tracker -c "CREATE EXTENSION postgis;"

cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m app.gtfs_static     # downloads and loads the feed, ~60s
.venv/bin/uvicorn app.main:app --port 8010
```

```bash
cd frontend
npm install && npm run dev              # localhost:5173
```

The static load handles 2.2M stop_times, 1,156 route shapes, and 2.2M derived
stop offsets. Re-run it when the MBTA publishes a new feed (roughly weekly); it
drops and rebuilds every table.

### Tests

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest        # estimator rules; creates a tracker_test DB

cd frontend
npm test                          # delay scale, formatting, chart helpers
```

## Deployment

The poller writes and the API only reads. In production they run as separate
processes; otherwise every API replica would poll the same feeds and write the
same rows.

```bash
RUN_POLLER=false uvicorn app.main:app --port 8010   # API, any number of these
python -m app.poller                                # exactly one of these
```

`RUN_POLLER` defaults to true so a single local process still works unchanged.
The poller records its state to `feed_meta` each cycle, so `/api/analytics/health`
reports the real poller regardless of which process it runs in.

| Concern | Handling |
|---|---|
| Load balancer probe | `GET /healthz` — one `SELECT 1`. `/api/analytics/health` runs unbounded counts and is diagnostic only |
| Read load | Responses cached for `CACHE_TTL_S` (default 5s), so database load follows the poll interval rather than request volume |
| CORS | Unnecessary if the built frontend and the API share an origin behind one reverse proxy; the frontend calls `/api` relatively. Otherwise set `CORS_ORIGINS` |
| Interactive docs | `ENABLE_DOCS=false` removes `/docs`, `/redoc`, and `/openapi.json` |
| Disk | ~7 GB steady state. Alert on table size: a stalled prune is silent otherwise |

Re-running `app.gtfs_static` drops and rebuilds every table, so the weekly feed
reload is a brief outage: vehicles render without delays until the offsets
finish. If that window matters, build into a new schema and swap.

## Known limitations

- Delay computation requires `current_stop_sequence`. Vehicles reporting a
  position without one appear on the map unfilled, carrying no delay figure.
- Trips added in realtime (`schedule_relationship: ADDED`) have no static
  schedule to compare against and are skipped by the estimator.
- Fleet size varies by a factor of three across the service day (231 distinct
  vehicles overnight against 765 at morning peak), and agreement with the feed
  is measurably weaker at peak. Any single-window figure should be read against
  the service level it was sampled from.
- `PROJECTED_SRID` is specific to Massachusetts. Targeting another city requires
  selecting the appropriate local metre-based CRS, not only changing the feed
  URLs.
- `npm audit` reports advisories in Vite's toolchain. They affect the
  development server rather than the production bundle, and the dev server binds
  to 127.0.0.1. The set changes over time, so re-run the audit rather than
  trusting this note.
- `backend/tests` covers the estimator's rules — the layover floor,
  interpolation, ratio clamping, the feed join, the confidence flags — against
  a synthetic route in a real PostGIS database. The static loader and the
  poller are exercised only by running them.
- The feed comparison is null when no prediction falls within five minutes of an
  observation, rather than reaching for a more distant one. Those rows still
  carry a computed delay, just nothing to compare it against.
- Read endpoints are cached for `CACHE_TTL_S`, so a response can trail the
  poller by a few seconds on top of the feed's own age.
