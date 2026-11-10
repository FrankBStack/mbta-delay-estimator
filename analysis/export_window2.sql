SET default_transaction_read_only = on;
SET max_parallel_workers_per_gather = 0;
SET statement_timeout = '3600s';
-- Replication window, all days but the November 11 holiday: every bus that stopped (arrival_score) or went by
-- (stop_pass). For a pass, the pass time stands in for both arrival and departure; a pass already scored as an
-- arrival is left out. The arrivals-only file for the secondary versions is the rows with kind = 'arrival'.
COPY (
WITH visits AS (
    SELECT 'arrival' AS kind, a.start_date, a.route_id, a.direction_id, a.trip_id, a.stop_sequence, a.stop_id,
           a.scheduled_time, a.scheduled_departure, a.arrived_at, a.departed_at, a.feed_300
    FROM arrival_score a
    UNION ALL
    SELECT 'pass', p.start_date, p.route_id, p.direction_id, p.trip_id, p.stop_sequence, p.stop_id,
           p.scheduled_time, p.scheduled_departure, p.passed_at, p.passed_at, p.feed_300
    FROM stop_pass p
    WHERE NOT EXISTS (SELECT 1 FROM arrival_score a
                      WHERE a.trip_id = p.trip_id AND a.start_date = p.start_date AND a.stop_sequence = p.stop_sequence)
)
SELECT v.kind, v.start_date, v.route_id, v.direction_id, v.trip_id, t.shape_id, v.stop_sequence, v.stop_id,
       v.scheduled_time, v.scheduled_departure, v.arrived_at, v.departed_at,
       round(extract(epoch FROM v.arrived_at - v.scheduled_time))::int AS late_s, v.feed_300, o.frac,
       o.arrival_s - og.origin_dep_s AS sched_s_from_origin
FROM visits v JOIN route r USING (route_id)
LEFT JOIN trip t ON t.trip_id = v.trip_id
LEFT JOIN trip_stop_offset o ON o.trip_id = v.trip_id AND o.stop_sequence = v.stop_sequence
LEFT JOIN (SELECT DISTINCT ON (trip_id) trip_id, departure_s AS origin_dep_s FROM trip_stop_offset ORDER BY trip_id, stop_sequence) og
       ON og.trip_id = v.trip_id
WHERE r.route_type = 3 AND v.start_date BETWEEN '2026-10-26' AND '2026-11-20' AND v.start_date <> '2026-11-11'
) TO STDOUT WITH CSV HEADER;
