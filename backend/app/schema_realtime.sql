-- Realtime tables: what the poller writes and the API reads. Every statement
-- is IF NOT EXISTS, so this file is safe to run on every process start (db.py
-- does) and on every feed reload; nothing here is ever dropped. schema.sql
-- must have run first, for postgis and gtfs_ts().

CREATE TABLE IF NOT EXISTS vehicle_position (
    id                    bigserial PRIMARY KEY,
    vehicle_id            text NOT NULL,
    label                 text,
    trip_id               text,
    route_id              text,
    direction_id          smallint,
    start_date            date,
    ts                    timestamptz NOT NULL,
    geom                  geometry(Point, 4326) NOT NULL,
    geom_p                geometry(Point, 26986) NOT NULL,
    bearing               real,
    speed                 real,
    current_status        text,
    current_stop_sequence integer,
    stop_id               text,
    UNIQUE (vehicle_id, ts)
);
CREATE INDEX IF NOT EXISTS vehicle_position_ts_idx    ON vehicle_position (ts DESC);
CREATE INDEX IF NOT EXISTS vehicle_position_trip_idx  ON vehicle_position (trip_id, ts DESC);
CREATE INDEX IF NOT EXISTS vehicle_position_geom_idx  ON vehicle_position USING gist (geom);

-- The agency's predictions, per trip/stop, with delay_s derived at insert time
-- (the feed has no delay field of its own).
CREATE TABLE IF NOT EXISTS trip_update (
    trip_id       text NOT NULL,
    stop_sequence integer NOT NULL,
    stop_id       text,
    route_id      text,
    start_date    date,
    ts            timestamptz NOT NULL,
    arrival_time  timestamptz,
    departure_time timestamptz,
    delay_s       integer,
    PRIMARY KEY (trip_id, stop_sequence, ts)
);
-- delay_s pairs the predicted arrival with the scheduled arrival (departure
-- with departure where the prediction has no arrival); departure_delay_s
-- pairs departure with departure, for vehicles measured against a departure.
ALTER TABLE trip_update ADD COLUMN IF NOT EXISTS departure_delay_s integer;
-- the (trip_id, stop_sequence, ts) PK already covers the per-stop lookup
CREATE INDEX IF NOT EXISTS trip_update_ts_idx ON trip_update (ts DESC);

-- One row per placeable observation. computed_delay_s is ours, feed_delay_s is
-- theirs, divergence_s is what we actually care about.
CREATE TABLE IF NOT EXISTS delay_observation (
    id               bigserial PRIMARY KEY,
    vehicle_id       text NOT NULL,
    trip_id          text NOT NULL,
    route_id         text NOT NULL,
    direction_id     smallint,
    ts               timestamptz NOT NULL,
    frac             double precision NOT NULL,
    snap_error_m     double precision NOT NULL,
    scheduled_time   timestamptz NOT NULL,
    computed_delay_s integer NOT NULL,
    feed_delay_s     integer,
    divergence_s     integer,
    method           text NOT NULL,
    confidence       text NOT NULL,     -- high | medium | low
    UNIQUE (vehicle_id, ts)
);
CREATE INDEX IF NOT EXISTS delay_observation_route_ts_idx ON delay_observation (route_id, ts DESC);
CREATE INDEX IF NOT EXISTS delay_observation_ts_idx       ON delay_observation (ts DESC);

-- The MBTA's prediction for a stop, kept at the moments its countdown read one
-- of a few fixed values (app.services.scoring.HORIZONS_S), so arrivals can be
-- scored by horizon without storing every prediction for every stop. lead_s
-- is what the countdown said at ts; the row is replaced whenever a later poll
-- lands closer to its horizon.
CREATE TABLE IF NOT EXISTS prediction_sample (
    trip_id        text NOT NULL,
    start_date     date NOT NULL,
    stop_sequence  integer NOT NULL,
    horizon_s      integer NOT NULL,
    ts             timestamptz NOT NULL,
    predicted_time timestamptz NOT NULL,
    lead_s         integer NOT NULL,
    PRIMARY KEY (trip_id, start_date, stop_sequence, horizon_s)
);
CREATE INDEX IF NOT EXISTS prediction_sample_ts_idx ON prediction_sample (ts DESC);

-- One row per observed arrival: the vehicle's first STOPPED_AT report at a
-- stop it was seen approaching. For a countdown reading of h seconds, feed_h
-- is the feed's predicted arrival minus the actual one, and position_h the
-- same for the arrival implied by the vehicle's position-derived delay at the
-- moment that prediction was issued. Negative means the vehicle came later
-- than the estimate said; NULL means no estimate existed at that reading.
CREATE TABLE IF NOT EXISTS arrival_score (
    id             bigserial PRIMARY KEY,
    vehicle_id     text NOT NULL,
    trip_id        text NOT NULL,
    route_id       text NOT NULL,
    direction_id   smallint,
    start_date     date NOT NULL,
    stop_sequence  integer NOT NULL,
    stop_id        text,
    scheduled_time timestamptz NOT NULL,
    arrived_at     timestamptz NOT NULL,
    feed_60        integer, position_60   integer,
    feed_120       integer, position_120  integer,
    feed_300       integer, position_300  integer,
    feed_600       integer, position_600  integer,
    feed_900       integer, position_900  integer,
    feed_1200      integer, position_1200 integer,
    UNIQUE (vehicle_id, trip_id, start_date, stop_sequence)
);
CREATE INDEX IF NOT EXISTS arrival_score_arrived_idx ON arrival_score (arrived_at DESC);
CREATE INDEX IF NOT EXISTS arrival_score_route_idx   ON arrival_score (route_id, arrived_at DESC);

-- arrival_score rolled up by service day, route, horizon and hour of day.
-- Kept indefinitely; arrival_score itself is pruned after SCORE_RETENTION_DAYS.
CREATE TABLE IF NOT EXISTS arrival_score_daily (
    day                 date NOT NULL,
    route_id            text NOT NULL,
    horizon_s           integer NOT NULL,
    hour                smallint NOT NULL,
    arrivals            integer NOT NULL,
    feed_n              integer NOT NULL,
    feed_mean_s         integer,
    feed_mean_abs_s     integer,
    feed_within_60      integer NOT NULL,
    feed_within_120     integer NOT NULL,
    position_n          integer NOT NULL,
    position_mean_s     integer,
    position_mean_abs_s integer,
    position_within_60  integer NOT NULL,
    position_within_120 integer NOT NULL,
    PRIMARY KEY (day, route_id, horizon_s, hour)
);
