-- MBTA tracker schema: the extension, the time helper and the feed metadata.
-- Idempotent, run by every feed load. The static tables are in
-- schema_static.sql and the realtime tables in schema_realtime.sql.
--
-- Two SRIDs throughout: 4326 for anything the feeds speak or MapLibre renders,
-- 26986 (Mass State Plane, meters) for anything we measure with. Doing the
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

CREATE TABLE IF NOT EXISTS feed_meta (
    key   text PRIMARY KEY,
    value text NOT NULL
);
