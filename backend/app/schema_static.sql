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
