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

The reload builds a fresh set of static tables in a staging schema, computes
the offsets there, and swaps the set in with one short transaction, so the
live tables are never empty and a load that fails part-way changes nothing.
The swap needs an exclusive lock on each table; a running query holds it off
for up to five seconds, after which the loader waits and tries again rather
than queue every reader behind it. Observations are left alone throughout.

Trip ids change with every MBTA rating, so a stale static feed shows up as
vehicles quietly losing their delay. The poller warns when the loaded feed's
`feed_end_date` has passed or fewer than half of the scheduled trips it sees
match, and `/api/analytics/health` reports both.

## Docker

The schema is applied when the database volume is first created, so the API
and poller start before the feed has been loaded. nginx serves the built
frontend and proxies `/api` to the API container on the same origin, so no
CORS configuration is needed.

`deploy/update.sh` is what the box runs: pull, build with fresh base images,
restart. `deploy/crontab` is its crontab, with the weekly reload and backup.
CI also publishes amd64 and arm64 images on every push to main, for a box
that would rather `docker compose pull` than build.

The schema is in three files. `schema.sql` holds the extension, `gtfs_ts()`
and `feed_meta`, all idempotent. `schema_static.sql` holds the static tables;
a feed load creates them in a staging schema and swaps them in, so it is only
run directly into an empty database. `schema_realtime.sql` holds the realtime
tables, every statement `IF NOT EXISTS`, and every process runs it at
startup, so a deploy that adds a realtime table or column needs no migration
step.

## Arrival scoring

Both arrival estimates, the feed's prediction and the position-derived one,
are scored against the arrivals that follow. The poller keeps a prediction
sample whenever a countdown reads 1, 2, 5, 10, 15 or 20 minutes
(`prediction_sample`), and an hourly pass in the same process finds arrivals
that settled half an hour ago, pairs each sample with the estimator's figure
from the same moment, and writes one row per arrival (`arrival_score`, one
column pair per horizon) plus a rollup by service day, route, horizon and
hour (`arrival_score_daily`). `app/services/scoring.py` has the definitions;
`/api/analytics/health` reports `arrivals_scored_24h`.

An arrival is the vehicle's first `STOPPED_AT` report at a stop it was seen
approaching on the same trip. Origins are excluded (a layover, not an
arrival), as are vehicles first seen already stopped, trips missing from the
static feed, and stops the vehicle passed without reporting a stop. Errors are
estimate minus actual, so negative means the vehicle came later than the
estimate said.

Retention: per-arrival rows for `SCORE_RETENTION_DAYS` (default 60, roughly
45 MB a day on the MBTA), samples for `SAMPLE_RETENTION_H` (default 24), the
rollup indefinitely. Each pass looks back `SCORE_LOOKBACK_H` hours (default
3) and skips arrivals already scored, so a restart loses nothing inside that
window. A pass that runs past `SCORE_TIMEOUT_S` (default 600) is abandoned and
retried next hour, and pruning runs before scoring, so a failing pass cannot
stall it. `/api/analytics/health` reports the last successful pass and the
last error under `poller`, and the page banner says when scoring is failing.
To catch up after a longer gap, within what the 48-hour position retention
still holds:

```bash
python -m app.services.scoring --hours 20
```

The wide table unpivots with a `VALUES` list; for example, the share of
readings within a minute by horizon over the last week:

```sql
SELECT h.horizon_s,
       count(h.feed)                                       AS feed_n,
       round(100.0 * count(*) FILTER (WHERE abs(h.feed) <= 60) / count(h.feed), 1) AS feed_within_60_pct,
       round(100.0 * count(*) FILTER (WHERE abs(h.position) <= 60) / count(h.position), 1) AS position_within_60_pct
FROM arrival_score a
CROSS JOIN LATERAL (VALUES (60, feed_60, position_60), (120, feed_120, position_120),
                           (300, feed_300, position_300), (600, feed_600, position_600),
                           (900, feed_900, position_900), (1200, feed_1200, position_1200))
     AS h(horizon_s, feed, position)
WHERE a.arrived_at > now() - interval '7 days'
GROUP BY 1 ORDER BY 1;
```

## Disk

The database is bounded by retention: positions and observations for
`RETENTION_HOURS`, predictions for `BACKFILL_HOURS`, samples for
`SAMPLE_RETENTION_H`, per-arrival scores for `SCORE_RETENTION_DAYS`. Only
the daily rollup grows without limit, at about a megabyte a day.
`/api/analytics/health` reports the size of each realtime table under
`storage`, and the page warns when the disk is under a tenth free.

What is not bounded is Docker. Each pull leaves the previous image behind
and each build leaves layers in the cache, so run `docker image prune -f`,
or `docker builder prune -f` after a build, once a deploy is up. Container
logs are capped in compose at three 20 MB files per service, except the
database, which is left on the default so a compose change there never
restarts Postgres.

## Backup

`deploy/backup.sh` runs nightly from the crontab. It dumps
`arrival_score_daily`, the one table nothing can regenerate, and the last
two days of `arrival_score`, which is kept for 60 days but built from 48
hours of positions, so it can't be rebuilt either past that. Dumps older
than two weeks are deleted from `backups/`.

Dumps on the same disk are not a backup. Set `BACKUP_URL` in `.env` to a
bucket's pre-authenticated request URL (Oracle Object Storage: create a PAR
on the bucket with object write permission, and use its URL up to and
including `/o/`) and each file is uploaded with a plain `PUT`; nothing on
the box needs credentials.

To restore into a fresh database, start the stack so the schema exists, then:

```bash
gunzip -c backups/rollup-2026-09-27.sql.gz | docker compose exec -T db psql -U tracker -d tracker
gunzip -c backups/arrivals-2026-09-27.csv.gz | docker compose exec -T db psql -U tracker -d tracker \
    -c "\copy arrival_score FROM STDIN WITH CSV HEADER"
```

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
