-- Static GTFS tables. A feed load builds a fresh set of these in a staging
-- schema (app.gtfs_static) and swaps them in with one short transaction, so
-- the live tables are never empty and a failed load changes nothing. Run
-- as-is only into an empty database. schema.sql must have run first, for
-- postgis and gtfs_ts().

CREATE TABLE route (
    route_id         text PRIMARY KEY,
    route_short_name text,
    route_long_name  text,
    route_type       smallint NOT NULL,
    route_color      text,
    route_text_color text,
    route_sort_order integer
);

-- Nothing queries by location, so no spatial indexes: every lookup is by id.
CREATE TABLE stop (
    stop_id   text PRIMARY KEY,
    stop_name text,
    geom      geometry(Point, 4326) NOT NULL,
    geom_p    geometry(Point, 26986) NOT NULL
);

CREATE TABLE shape (
    shape_id text PRIMARY KEY,
    geom     geometry(LineString, 4326) NOT NULL,
    geom_p   geometry(LineString, 26986) NOT NULL
);

-- The service calendar isn't loaded: the realtime feed says which service
-- date a trip is running on, which is all the estimator needs.
CREATE TABLE trip (
    trip_id       text PRIMARY KEY,
    route_id      text NOT NULL REFERENCES route(route_id),
    shape_id      text REFERENCES shape(shape_id),
    direction_id  smallint,
    trip_headsign text
);
CREATE INDEX trip_route_idx ON trip (route_id);

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

-- How far along its trip's shape each scheduled stop sits, 0..1. GTFS has a
-- field for this and the MBTA never fills it in, so app.offsets derives it.
-- On loops and out-and-backs the fractions can run backwards with
-- stop_sequence; the estimator checks that per leg (delay.py).
CREATE TABLE trip_stop_offset (
    trip_id        text NOT NULL,
    stop_sequence  integer NOT NULL,
    stop_id        text NOT NULL,
    frac           double precision NOT NULL,
    arrival_s      integer,
    departure_s    integer,
    PRIMARY KEY (trip_id, stop_sequence)
);
-- matching an added trip to a scheduled one starts from the stop it is at
CREATE INDEX trip_stop_offset_stop_idx ON trip_stop_offset (stop_id);
