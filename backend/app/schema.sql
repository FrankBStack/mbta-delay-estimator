-- MBTA tracker schema.
--
-- Two SRIDs throughout: 4326 for anything the feeds speak or MapLibre renders,
-- 26986 (Mass State Plane, metres) for anything we measure with. Doing the
-- distance work in degrees skews it badly enough to matter.

CREATE EXTENSION IF NOT EXISTS postgis;

-- (service_date, seconds-after-midnight) -> a real instant.
--
-- Noon minus twelve hours rather than plain midnight, which is how the GTFS
-- spec defines it and the only version that survives a DST changeover. The
-- offset regularly goes past 86400 (a 00:50 departure ships as 24:50:00 on the
-- previous service day), so this cannot be a timestamp column.
CREATE OR REPLACE FUNCTION gtfs_ts(service_date date, secs integer, tz text)
RETURNS timestamptz AS $$
    SELECT ((service_date + time '12:00') AT TIME ZONE tz)
           - interval '12 hours'
           + (secs * interval '1 second')
$$ LANGUAGE sql STABLE;


DROP TABLE IF EXISTS delay_observation, trip_update, vehicle_position,
    trip_stop_offset, stop_time, trip, shape, stop, route,
    calendar_date, calendar, feed_meta CASCADE;

CREATE TABLE route (
    route_id         text PRIMARY KEY,
    route_short_name text,
    route_long_name  text,
    route_type       smallint NOT NULL,
    route_color      text,
    route_text_color text,
    route_sort_order integer
);

CREATE TABLE stop (
    stop_id   text PRIMARY KEY,
    stop_name text,
    parent_station text,
    geom      geometry(Point, 4326) NOT NULL,
    geom_p    geometry(Point, 26986) NOT NULL
);
CREATE INDEX stop_geom_idx ON stop USING gist (geom);

CREATE TABLE shape (
    shape_id text PRIMARY KEY,
    geom     geometry(LineString, 4326) NOT NULL,
    geom_p   geometry(LineString, 26986) NOT NULL,
    length_m double precision NOT NULL
);
CREATE INDEX shape_geom_idx ON shape USING gist (geom);

CREATE TABLE trip (
    trip_id       text PRIMARY KEY,
    route_id      text NOT NULL REFERENCES route(route_id),
    service_id    text NOT NULL,
    shape_id      text REFERENCES shape(shape_id),
    direction_id  smallint,
    trip_headsign text
);
CREATE INDEX trip_route_idx   ON trip (route_id);
CREATE INDEX trip_service_idx ON trip (service_id);

-- arrival_s / departure_s are raw seconds after the service day's midnight and
-- can exceed 86400. See gtfs_ts() above.
CREATE TABLE stop_time (
    trip_id       text NOT NULL,
    stop_sequence integer NOT NULL,
    stop_id       text NOT NULL,
    arrival_s     integer,
    departure_s   integer,
    PRIMARY KEY (trip_id, stop_sequence)
);

CREATE TABLE calendar (
    service_id text PRIMARY KEY,
    monday smallint, tuesday smallint, wednesday smallint, thursday smallint,
    friday smallint, saturday smallint, sunday smallint,
    start_date date NOT NULL,
    end_date   date NOT NULL
);

CREATE TABLE calendar_date (
    service_id     text NOT NULL,
    date           date NOT NULL,
    exception_type smallint NOT NULL,   -- 1 added, 2 removed
    PRIMARY KEY (service_id, date)
);

CREATE TABLE feed_meta (
    key   text PRIMARY KEY,
    value text NOT NULL
);

-- How far along its trip's shape each scheduled stop sits, 0..1. GTFS has a
-- field for this and the MBTA never fills it in, so app.offsets derives it.
--
-- frac_monotonic is false where the fractions don't increase with
-- stop_sequence, which happens on loops and out-and-backs. Those trips can't
-- be interpolated by fraction alone.
CREATE TABLE trip_stop_offset (
    shape_id       text NOT NULL,
    trip_id        text NOT NULL,
    stop_sequence  integer NOT NULL,
    stop_id        text NOT NULL,
    frac           double precision NOT NULL,
    dist_m         double precision NOT NULL,
    snap_error_m   double precision NOT NULL,  -- stop's distance from its own shape
    arrival_s      integer,
    departure_s    integer,
    frac_monotonic boolean NOT NULL,
    PRIMARY KEY (trip_id, stop_sequence)
);
CREATE INDEX trip_stop_offset_trip_frac_idx ON trip_stop_offset (trip_id, frac);

CREATE TABLE vehicle_position (
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
CREATE INDEX vehicle_position_ts_idx    ON vehicle_position (ts DESC);
CREATE INDEX vehicle_position_trip_idx  ON vehicle_position (trip_id, ts DESC);
CREATE INDEX vehicle_position_geom_idx  ON vehicle_position USING gist (geom);

-- The agency's predictions, per trip/stop, with delay_s derived at insert time
-- (the feed has no delay field of its own).
CREATE TABLE trip_update (
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
-- the (trip_id, stop_sequence, ts) PK already covers the per-stop lookup
CREATE INDEX trip_update_ts_idx ON trip_update (ts DESC);

-- One row per placeable observation. computed_delay_s is ours, feed_delay_s is
-- theirs, divergence_s is what we actually care about.
CREATE TABLE delay_observation (
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
CREATE INDEX delay_observation_route_ts_idx ON delay_observation (route_id, ts DESC);
CREATE INDEX delay_observation_ts_idx       ON delay_observation (ts DESC);
