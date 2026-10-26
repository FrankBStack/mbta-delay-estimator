# Capstone analysis

Stop- and route-level comparison of bus lateness and MBTA prediction error across
Boston-area neighborhoods, from the tracker's arrival log.

## Inputs

Exported from the production database (read-only `\copy`), into `data/`:

- `arrivals_window1.csv.gz`: one row per bus arrival, September 28 to October 23, 2026,
  all days (`export_window1.sql` is the query)
- `stops.csv`, `routes.csv`, `shapes_bus.csv`, `trips_bus.csv`: the loaded GTFS tables

Public layers, also in `data/`:

- `tl_2024_25_bg/`: TIGER 2024 block groups for Massachusetts
- `acsdt5y2024-b19013.dat`: ACS 2020–2024 median household income, table-based summary file
- `ej2020/`: MassGIS 2020 Environmental Justice Populations

## Run

```bash
.venv/bin/python prep_neighborhoods.py      # stops and shapes joined to block groups, race shares, timepoints
.venv/bin/python analyze.py data/arrivals_window1.csv.gz output/window1_v2
.venv/bin/python checks.py data/arrivals_window1.csv.gz output/window1_v2 2026-10-14 2026-10-23
.venv/bin/python checks_timepoint_early.py data/arrivals_window1.csv.gz output/window1_v2
.venv/bin/python checks_route_influence.py data/arrivals_window1.csv.gz
.venv/bin/python checks_after_timepoint.py data/arrivals_window1.csv.gz
.venv/bin/python maps.py output/window1_v2
```

`analyze_v1.py` is the first version, kept for comparison: it adjusted stops by subtracting cell means,
which pulls gaps toward zero, and resampled days only.

`analyze.py` writes the tables (`table_*.csv`), `hotspots.csv` and `results.json`;
`maps.py` draws the four maps; `write_results.py` summarizes the tables as `results.md`. The replication window (October 26 to November 20) is
the same three commands on a second export, with the scripts unchanged.

## Method, in brief

- A late arrival is more than five minutes after the scheduled time; prediction error is the
  absolute error of the MBTA's prediction five minutes before arrival.
- Stops with fewer than 100 weekday arrivals are left out (sensitivity at 50 and 200).
- Within-route comparisons subtract each arrival's route × direction × position-bin mean
  (position = scheduled minutes from the trip origin), so a stop is compared with the same
  route at the same point along it.
- Confidence intervals resample whole service days (stop level) or routes (route level).
- Hot spots: Getis-Ord Gi* with a 500 m binary distance band, FDR-corrected at 0.05.

## Primary comparisons (fixed 2026-10-25)

These were fixed after the main estimates table of `analyze.py` had been seen, but before the timepoint
and sensitivity results were read. They follow the three hypotheses as written in the outline on
2026-10-20, under the two state
Environmental Justice criteria (income, minority), for the two original measures:

- H1: route level, lateness and prediction error (4 estimates)
- H2: lateness, within route and position (2 estimates)
- H3: prediction error, within route and position (2 estimates)

Eight primary estimates in all, reported with bootstrap p-values and a Holm correction across the eight.
Everything else is exploratory: early arrivals, the federal minority rule, the continuous income and race
measures, the unadjusted and route-only columns, the hot spots, and the sensitivity and timepoint checks.

The federal Title VI minority rule (block groups above the service area's 43.8% minority share) is a
secondary test. It leaves 58 unflagged routes against 13 under the state criterion, so it is the
better-powered route test, but it was added after the primary tests were chosen.

## November replication (fixed 2026-10-26, before any November data was read)

Window: weekdays from October 26 to November 20, 2026, excluding November 11. The scripts above are run
unchanged on the second export, and the eight primary tests are reported again. Scoring has recorded
`departed_at` (the last stopped report at each stop), `scheduled_departure`, `pred_300_at` and
`pred_300_seq` since 2026-10-26 03:30 UTC (tracker commit 5b993c4).

- **H4 (primary for November).** Stops in block groups meeting the state Environmental Justice income
  criterion have a higher share of departures more than 60 s before the scheduled departure than other
  stops. Arrival-weighted and unadjusted; 95% intervals resample days and routes. A departure is the last
  stopped report (`departed_at`), which runs a few seconds early for every stop alike.
- **H4a (secondary).** The gap is concentrated on routes 15, 23 and 66: dropping those three routes cuts it
  by more than half.
- **H4b (secondary).** Within route x direction x position cells, the gap is indistinguishable from zero.

Decision rule: H4 is supported if its 95% interval excludes zero in the stated direction.

## Amendment to the November hypotheses (fixed 2026-10-26, before any November data was read)

Two problems found on 2026-10-26 with the MBTA's own September 28-30 timepoint records
(`checks_mbta_september.py`, `checks_schedule_standard.py`):

- Routes 15, 23 and 66, which drove the October early-arrival gap, are on the MBTA's headway standard
  (about 99% of their timepoint records): the agency judges them by gaps between buses, not by the timetable.
  Flagged stops sit on headway-run trips far more often than unflagged stops (income criterion: 39.7% of
  arrivals against 24.8%).
- Buses that pass a stop without stopping are not logged. Unlogged MBTA timepoint departures are more often
  early (11.5% against 7.1%), and more are missed at unflagged stops (29.6% against 16.5%).

H4, H4a and H4b above are replaced by the following. Each trip is judged by its own MBTA standard, taken from
the MBTA's file: `data/trip_standard.csv` maps GTFS trip ids to the standard of their matched September 28-30
timepoint events; trips not in it take their route's majority standard in that file.

A bus's time at a stop is its last stopped report (`departed_at`) or, for a bus that passed without stopping,
the pass time (`stop_pass.passed_at`, interpolated along the route shape between the position reports on
either side of the stop; logged from 2026-10-26, with October 26 rebuilt from retained positions).

- **H4 (amended, primary).** On timetable-run trips (schedule standard), stops in block groups meeting the
  state Environmental Justice income criterion have a higher share of buses leaving more than 60 s before the
  scheduled departure than other stops.
- **H5 (new, primary).** On headway-run trips (headway standard), the same stops have a higher share of long
  gaps: time since the previous bus on the same route and direction at the stop more than 1.5 times the
  scheduled gap to the previous *scheduled* trip, so dropped trips count as long gaps. The 1.5 threshold
  follows the MBTA's earlier Service Delivery Policy (150% of scheduled headway).
- **H4b, H5b (secondary).** The same comparisons within route x direction x position cells.

Both primaries are arrival-weighted and unadjusted, with 95% intervals that resample days and routes, and are
supported if the interval excludes zero in the stated direction. H4a is dropped: its routes are headway-run
and fall under H5.
