# MBTA Delay Estimator

[![CI](https://github.com/FrankBStack/mbta-delay-estimator/actions/workflows/ci.yml/badge.svg)](https://github.com/FrankBStack/mbta-delay-estimator/actions/workflows/ci.yml)

Real-time map of Boston transit vehicles. Delays are computed from each
vehicle's physical position against the published timetable, not read from the
agency feed.

Over a weekday evening peak the computed figure lands within a minute of the
MBTA's own prediction 88.8% of the time (σ 50s); see [Validation](#validation)
below. Those figures predate the dwell hold described under
[Placing a vehicle on its route](#placing-a-vehicle-on-its-route) and will be
re-measured.

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
The feed's `current_stop_sequence` picks which leg the vehicle is on. Where that
leg's stop fractions run backwards, an in-transit vehicle can't be placed along
it and the observation is dropped rather than scored against the wrong stop;
stopped-at and layover observations don't depend on the fraction and are kept.

Each observation records which method produced it:

| Method | Description |
|---|---|
| `interpolated` | In transit; scheduled time prorated along the shape between two stops |
| `stopped_at` | Stopped at a mid-route stop; the deviation at the moment it arrived, held for the dwell |
| `layover` | Stopped at the trip's first stop; measured against scheduled departure, floored at zero |
| `first_stop` | Approaching the first stop, with no preceding stop to interpolate from; floored at zero |

The MBTA schedules arrival equal to departure at all but 92 of its 2.2M stop
times, so boarding time is folded into the travel segments. Measured against
the clock, a vehicle sitting at a stop would read one second later for every
second it dwells, then appear to catch up along the next leg. `stopped_at`
therefore measures the deviation once, when the vehicle first reports itself
stopped, and holds it until it moves. The catch-up along the leg remains, and
is real: the timetable does expect the vehicle to have left.

A vehicle waiting at its origin ahead of departure reads as exactly zero. That
says nothing about lateness, so the headline median and the analytics leave
those out and the headline counts them separately.

Observations are marked low confidence where the vehicle sits more than 150m
from the shape it reports running, or where the result exceeds three hours —
typically indicating a mismatched service date. These are retained but excluded
from analytics by default.

Stop-to-shape snap error across the loaded feed: mean 7.0m, p95 11.9m.

## Validation

Since the MBTA publishes no delay field, its figure is derived for comparison
from the same trip and stop: predicted arrival against scheduled arrival, or
predicted departure against scheduled departure for a vehicle on layover, which
is measured against its departure. Over a weekday evening peak (87,461 paired
observations) the two agreed to within 60s 88.8% of the time, with σ 50s and a
mean divergence of +19s. Most of that offset came from comparing a dwelling
vehicle's clock reading against the feed's recorded arrival; the dwell hold
above removes it. They answer different questions (ours is how late a vehicle
is right now, theirs is how late it will be on arrival), so they diverge most
at peak service.

Correlation is reported but is a weak test here. Both figures share the same
schedule baseline and vehicle position, and delays span several minutes, so an
r above 0.99 is nearly guaranteed. The divergence statistics are thinned to one
observation per vehicle per minute; consecutive 15s reports from one vehicle
are near-duplicates.

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
  backfill.py       recompute observations from stored positions
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

## Running with Docker

```bash
docker compose up -d --build           # PostGIS, API, poller, and the frontend on localhost:8080
docker compose run --rm load           # downloads and loads the feed, ~60s; repeat weekly
```

The schema is applied when the database volume is first created, so the API
and poller start before the feed has been loaded; vehicles simply carry no
delay until `load` finishes. nginx serves the built frontend and proxies
`/api` to the API container on the same origin, so no CORS configuration is
needed.

## Running locally

Requires PostgreSQL with PostGIS, Python 3.11+, and Node 22+.

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

### Tests

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest        # estimator rules; creates a tracker_test DB

cd frontend
npm test                          # delay scale, formatting, chart helpers
```

CI runs both suites and builds the Docker images on every push. Point the
backend tests at another database with `TEST_ADMIN_URL` and `TEST_DATABASE_URL`.

## Deployment

The poller writes and the API only reads. In production they run as separate
processes; otherwise every API replica would poll the same feeds and write the
same rows.

```bash
RUN_POLLER=false uvicorn app.main:app --port 8010   # API, any number of these
python -m app.poller                                # exactly one of these
python -m app.gtfs_static                           # weekly, when the MBTA publishes a new feed
python -m app.backfill                              # rescore stored positions after an estimator change
```

`RUN_POLLER` defaults to true so a single local process still works unchanged.
The poller records its state to `feed_meta` each cycle, so `/api/analytics/health`
reports the real poller regardless of which process it runs in.

The feed reload drops and rebuilds the static tables, leaving observations
alone, and is a brief outage: vehicles render without delays until the offsets
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
- Distance work is done in EPSG:26986, which is specific to Massachusetts.
- Trip ids change with every MBTA rating, so a stale static feed shows up as
  vehicles quietly losing their delay. The poller warns when the loaded feed's
  `feed_end_date` has passed or fewer than half of the scheduled trips it sees
  match, and `/api/analytics/health` reports both.
  Targeting another city means changing the SRID in `schema.sql` and
  `config.py`, not only the feed URLs.
- The feed comparison is null when no prediction falls within five minutes of an
  observation, rather than reaching for a more distant one. Those rows still
  carry a computed delay, just nothing to compare it against.
- Read endpoints are cached for `CACHE_TTL_S`, so a response can trail the
  poller by a few seconds on top of the feed's own age.
