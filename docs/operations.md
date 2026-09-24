# Operating the estimator

## Processes

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

A backfill deletes and rescores every observation in its window, and pairs
each one with the feed again from `trip_update`. Predictions are only kept
for `BACKFILL_HOURS`, so a backfill reaching past that, or past any manual
cleanup of `trip_update`, leaves those observations with a computed delay but
no feed comparison. Measure before you backfill if the comparison matters.
The poller records its state to `feed_meta` each cycle, so `/api/analytics/health`
reports the real poller regardless of which process it runs in.

## Feed reload

The reload drops and rebuilds the static tables, leaving observations alone,
and is a brief outage: vehicles render without delays until the offsets finish.
If that window matters, build into a new schema and swap.

Trip ids change with every MBTA rating, so a stale static feed shows up as
vehicles quietly losing their delay. The poller warns when the loaded feed's
`feed_end_date` has passed or fewer than half of the scheduled trips it sees
match, and `/api/analytics/health` reports both.

## Docker

The schema is applied when the database volume is first created, so the API
and poller start before the feed has been loaded. nginx serves the built
frontend and proxies `/api` to the API container on the same origin, so no
CORS configuration is needed.

CI publishes amd64 images only. On an arm64 host, `docker compose build`
before `up -d` rather than `pull`.

A code deploy does not touch the schema. `schema.sql` runs again only on a
feed reload, so a change to one of the realtime tables (the `IF NOT EXISTS`
statements at its end) has to be applied by hand with `psql` in the db
container, or by running the reload, before starting code that depends on it.
Running the whole file by hand is not an option: it drops and rebuilds the
static tables.

## Caching

Read endpoints are cached for `CACHE_TTL_S`, so a response can trail the poller
by a few seconds on top of the feed's own age.

## Tests

The backend tests create a `tracker_test` database. Point them at another
server with `TEST_ADMIN_URL` and `TEST_DATABASE_URL`.

## Another city

Distance work is done in EPSG:26986, which is specific to Massachusetts.
Targeting another city means changing the SRID in `schema.sql` and
`config.py`, not only the feed URLs.
