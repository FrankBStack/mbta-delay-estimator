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
- `MBTA_Bus_Arrival_Departure_Times_2026.zip`: the MBTA's 2026 bus arrival and departure file as downloaded on
  2026-11-10 (posted 2026-11-05, January to October). The September figures came from the download of
  2026-10-15 (January to September), kept as `MBTA_Bus_Arrival_Departure_Times_2026_through-sep.zip`; the MBTA
  has since reprocessed earlier months, so rerunning September on the new file can give slightly different numbers.
- `tiger_water/`: TIGER 2024 area water for Suffolk, Middlesex, Norfolk, Essex and Plymouth counties, and the
  Census cartographic state boundaries (`cb_2023_us_state_500k.zip`), for the map base layers and locator

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
`maps.py` draws the maps; `write_results.py` summarizes the tables as `results.md`.

The replication window (October 26 to November 20, less November 11), after November 20:

```bash
ssh opc@<server> 'cd /opt/tracker && docker compose exec -T db psql -q -U tracker -d tracker' \
    < export_window2.sql | gzip > data/visits_window2.csv.gz
gzip -dc data/visits_window2.csv.gz | awk -F, 'NR == 1 || $1 == "arrival"' | gzip > data/arrivals_window2.csv.gz
.venv/bin/python fetch_gtfs_archive.py 2026-10-26 2026-11-20
.venv/bin/python analyze.py data/visits_window2.csv.gz output/window2_main          # arrivals and passes
.venv/bin/python analyze.py data/arrivals_window2.csv.gz output/window2_arrivals   # arrivals only
.venv/bin/python november.py data/visits_window2.csv.gz output/window2 2026-10-26 2026-11-20 2026-11-11
```

`analyze.py` is unchanged; the export leaves out November 11, which `analyze.py` would otherwise count as a
weekday. `november.py` runs H4, H5, H4b and H5b and the coverage report.

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

## Second amendment (fixed 2026-10-26, before any November data was read)

`checks_coverage_bias.py` compared September 28-30 gaps on the MBTA's complete timepoint record with the same
gaps on the events our log has. Our arrival log misses more events at unflagged stops (29.6% against 16.5%
for the income criterion), and the missed events skew early. On the same events, our log shows an income
early-arrival gap of +2.7 points against +0.6 in the MBTA's record, and unadjusted lateness gaps 3-4 points
more favorable to flagged stops than the record shows. Within-route gaps moved by under about 1 point.
Prediction error cannot be checked this way (the MBTA's file has no predictions), so its October results
carry the same unmeasured risk.

**How the November rerun of the eight primary tests counts buses.** Main version: the lateness tests (H1 on
lateness, H2) count every bus that stopped (`arrival_score`) or went by (`stop_pass`); on October 26's
finished trips the two together cover 95.6% of scheduled stop visits. A pass is late or early by
`passed_at` against `scheduled_time`. Secondary version: arrivals only, exactly as run on October. The
prediction-error tests (H1 on prediction error, H3) use arrivals only in both versions, since passes carry no
prediction.

**How H4 and H5 classify trips** (replaces the trip map above, so the MBTA's November file is not needed).
A trip takes the MBTA's majority standard for its route, direction and scheduled hour in the MBTA's own
September 2026 weekday records (`make_standard_rule.py`: 17 days, 1.56 million records, 97.7% agreeing with
their cell's majority; MBTA "Outbound" is GTFS direction 0, checked on matched events). Cells with no records
fall back to the route and direction's majority, then the route's, then the timetable standard.

## Third amendment (fixed 2026-10-26, before any November data was read)

**Prediction tests count passes too.** Riders at a stop a bus goes by still saw its countdown, so a
five-minute prediction exists for passed stops. Since tracker commit e4a52ae (fix 77841c2), `stop_pass`
stores it (`pred_300_at`, `feed_300` = predicted minus passed time); October 26 was rebuilt while the
server still held that day's samples, and 96.2% of its passes carry one. For the November rerun, H1 on
prediction error and H3 use arrivals plus passes as the main version and arrivals only as the secondary,
like the lateness tests.

**Coverage is reported with every November result.** For flagged and unflagged stops separately: the share
of scheduled stop visits on trips that ran with an arrival, with a pass, and with neither; and the share
of scheduled trips with no logged event at all (trips that never ran or were never tracked). On October
26's finished trips that ran, 77.2% of scheduled visits had an arrival, 18.4% a pass and 4.4% neither.

**How the October results are to be read.** The October lateness tests (H1 and H2 on lateness) used a log
now known to understate flagged stops' lateness relative to the MBTA's complete record (by 2.8 points for
the income criterion and 3.9 for minority on the September 28-30 timepoint events; about three quarters of
that from missed events and the rest from timing arrivals rather than departures). They were biased toward
finding no difference, so the November main version is the first fair test. The MBTA's departure-based
gap is not the figure November should reproduce: an arrival-based test should come in below it even if
the pattern is real, because flagged stops hold buses longer.

## What November can and cannot settle (stated 2026-10-26, before any November data was read)

The MBTA's complete September record (17 weekdays, `checks_mbta_record_gaps.py`, exploratory) suggests a
lateness gap of about 3-4 points for minority areas (state criterion +3.7, interval -0.5 to +7.7; federal
rule +4.1, +0.1 to +8.4). It disappears when stops are compared within the same route and direction (-0.8),
so it comes from which routes serve those areas, not from where their stops sit along the routes.

The pre-specified test of a between-route gap is H1, and under the state criterion it compares 139 flagged
routes with only 13 unflagged ones: its October interval ran from -6.8 to +11.8 points. November's will be
about as wide, and an arrival-based test should come in below the MBTA's departure-based figure even if the
pattern is real. A November null on H1 therefore cannot rule out a 3-4 point gap between routes. The
federal-rule secondary (58 unflagged routes) is the only route test with a realistic chance of detecting
one, and it remains secondary. This study cannot settle the between-route question either way.

## Correction (2026-10-27)

`checks_mbta_september.py` and `checks_coverage_bias.py` joined the MBTA's records to our log on the raw
route id, but the MBTA's file names routes by zero-padded short name ("01", "SL1", "CT3") where GTFS uses
"1", "741", "708". Records for routes 1, 4, 7, 8, 9, the Silver Line and CT3 (14% of September 28-30
mid-route departures) could never match, so they were counted as missed. Both scripts now map the ids
(`analyze.gtfs_route_id`). Corrected figures for September 28-30:

- 84.7% of mid-route timepoint departures match a logged arrival (not 75%); unmatched departures are more
  often early (12.9% against 7.4%) and twice as common at unflagged stops (income 17.6% against 8.8%,
  minority 28.9% against 11.8%).
- The log understates the unadjusted lateness gap by 1.4 points (income, paired interval 0.2 to 2.6) and 1.8
  (minority, -0.7 to 4.3), not 2.8 and 3.9; about three quarters and half of that, respectively, from missed
  events. The log overstates the income early-arrival gap by 1.2 points (+0.2 to +2.4). Within-route gaps move by
  half a point or less. The log's income early-arrival gap on these days is +1.8 (not +2.7) against +0.6 in
  the MBTA's record.

The direction of every finding is unchanged, and no pre-registered decision depended on the size of the
bias. The H4/H5 classification rule (`make_standard_rule.py`) keys its cells on the MBTA's route ids, so the
November code must map them with `analyze.gtfs_route_id` before joining to GTFS trips; without it, routes 1,
4, 7, 8, 9, the Silver Line and CT3 would silently fall back to the timetable standard. With the mapping
and each trip's first scheduled hour, 40.4% of October weekday arrivals are on headway-standard trips.

This correction was made on 2026-10-27, after the November tests were fixed (tags `capstone-prespec-2026-10-26`
to `capstone-prespec-2026-10-26d`) and after the replication window began. It changes only how the MBTA's
records are matched, to our log and to GTFS route ids. No hypothesis, measure, threshold or decision rule
changes, and no data from the replication window was used in finding or checking it.

## October MBTA-record test (fixed 2026-10-27, before the MBTA published its October 2026 file)

The MBTA's complete September record (`checks_mbta_record_gaps.py`, exploratory; see the section above) suggests
a lateness gap between routes for minority areas that this study's log-based tests cannot settle. This section
fixes a test of it on the MBTA's October 2026 Bus Arrival Departure Times file, which had not been published when
this was written. The test days are the October days of the first analysis window, so they overlap neither the
September record that suggested the hypothesis nor the November replication window. Our log captured about 85% of
such departures on September 28-30, and its October results are already known; what is new is the MBTA's
complete record of these days, which the log's gaps understate (see the correction above).

- **H6 (primary).** On weekdays from October 1 to 23, 2026, excluding October 12, mid-route timepoint
  departures at stops in block groups flagged under the federal Title VI rule (minority share above the
  service area's 43.8%, `fta_minority`) are more often more than five minutes late than departures at other
  stops. The gap is flagged minus unflagged, over all trips, unadjusted, each departure counted once.
  September: +4.1 points (+0.1 to +8.4).
- **Decision rule.** H6 is supported if the lower end of its 95% interval is above zero. Intervals resample
  service days and routes together (500 draws).
- **Secondary, reported but not tested.** The same gap under the state minority and income criteria; within
  route and direction (September, federal rule: -0.1); on timetable-run trips only; and early departures.

Run, after downloading the 2026 file again once it includes October:
`python checks_mbta_record_gaps.py 2026-10 2026-10-01 2026-10-23 2026-10-12`. The script is the one that produced
the September figures, with options added for the last day and for days to skip; September's output is
unchanged. If the MBTA has not published October by December 4, 2026, the test is not run and the paper says
so. Nothing else about the October or November analyses changes.

## Data note: November 6 evening (2026-11-10, before any replication data was analyzed)

On Friday, November 6, between about 6 and 8 pm, about 45% of the bus visits normally logged as arrivals were
logged as passes instead: arrivals in those two hours fell from about 18,400 and 15,500 to 10,200 and 10,400,
and passes rose from about 3,700 to 10,300 and 8,700, so total stop visits were about the same as on other
days. The poller logged no errors, so the likely cause is the MBTA's vehicle feed reporting buses as in
transit rather than stopped; the raw positions for that evening have since been pruned. No day is excluded.
The main November versions count arrivals and passes together and are barely affected; the arrivals-only
secondary versions lose about 13,000 evening arrivals, under 0.3% of the window. This was found from daily
and hourly counts only; no comparison between areas had been made on replication data.

## October MBTA-record test: result (run 2026-11-10)

Run once, as written above, on the MBTA file posted 2026-11-05 and downloaded 2026-11-10, with
`checks_mbta_record_gaps.py` unchanged since tag `capstone-prespec-2026-10-27`: 16 weekdays, 1,012,644
mid-route timepoint departures.

- **H6: not supported.** Federal rule, all trips, unadjusted: +2.2 points (95% interval -1.6 to +5.9). The
  lower end is below zero. The gap points the same way as September's (+4.1) at about half the size.
- Secondary, not tests: state minority criterion +2.2 (-1.7 to +5.9); income -0.7 (-3.7 to +2.8). Within route
  and direction: federal -0.3, state minority -0.9, income -0.2, all intervals including zero. Timetable-run
  trips only: federal +1.4 (-1.6 to +4.8). Early departures, federal rule: -0.5 (-4.1 to +2.3).

## November code (fixed 2026-11-10, before any replication data was analyzed)

`export_window2.sql`, `fetch_gtfs_archive.py` and `november.py` were written and tested on October data (with
arrival times standing in for departures) and on three rows and row counts of October 26, with no comparison
between areas on replication data. The hypotheses above leave these choices open; they are fixed here:

- A pass counts at the pass time for arrival, departure and lateness. A pass on a trip and stop already scored as
  an arrival is dropped (30 of 67,830 on October 26).
- H4 and H5 use stops with 100 or more weekday visits in the window, as `analyze.py` does, and leave out each
  trip's first and last scheduled stop: the first is layover and the last has no departure.
- Scheduled visits come from the MBTA timetable version in effect each day (`archived_feeds.txt`). A visit not on
  that day's timetable is left out of H4 and H5 and counted under coverage.
- H5: a bus's gap is the time since the previous logged bus of the same route and direction at the stop that
  day; the scheduled gap is to the previous scheduled trip on that day's timetable. The first bus of the day at
  each stop has no gap. A bus the log missed makes the next bus's gap look long, so H5 is read with the coverage
  report beside it.
- Intervals: 1,000 draws resampling days and routes, seed 20261110. H4 and H5 are supported if the lower end of
  the 95% interval is above zero.
- Coverage: scheduled stop visits after each trip's first stop, by flag. Trips that ran are those with at least
  one logged visit that day; their visits are split into arrival, pass and neither, and the share of scheduled
  visits on trips with no logged visit is reported separately.
