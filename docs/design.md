# Estimator design notes

Detail behind the placement methods and confidence rules summarised in the
main README. The implementation is the single query in
`backend/app/services/delay.py`.

## Projection

All distance work runs in EPSG:26986 (NAD83 / Massachusetts Mainland, metres).
At Boston's latitude a degree of longitude is approximately 0.74 of a degree of
latitude, so locating a point on a line in unprojected WGS84 coordinates biases
the result east-west. The SRID is fixed in `schema.sql` and `config.py`.

Stop-to-shape snap error across the loaded feed: mean 7.0m, p95 11.9m.

## Loop routes

`ST_LineLocatePoint` returns the first nearest point on the line, so on a loop
route a vehicle on its second pass resolves to a position near the start. This
affects 2.6% of MBTA trips, flagged at load time as `frac_monotonic = false`.
The feed's `current_stop_sequence` picks which leg the vehicle is on. Where that
leg's stop fractions run backwards, an in-transit vehicle can't be placed along
it and the observation is dropped rather than scored against the wrong stop;
stopped-at and layover observations don't depend on the fraction and are kept.

## The dwell hold

The MBTA schedules arrival equal to departure at all but 92 of its 2.2M stop
times, so boarding time is folded into the travel segments. Measured against
the clock, a vehicle sitting at a stop would read one second later for every
second it dwells, then appear to catch up along the next leg. `stopped_at`
therefore measures the deviation once, when the vehicle first reports itself
stopped, and holds it until it moves. The catch-up along the leg remains, and
is real: the timetable does expect the vehicle to have left.

Before the dwell hold, the mean divergence from the feed was +19s; most of that
came from comparing a dwelling vehicle's clock reading against the feed's
recorded arrival. Measured on identical observations, the hold cut the
`stopped_at` class's mean absolute divergence from 30s to 11s at peak
([docs/validation.md](validation.md)).

The hold is capped at five minutes (`HOLD_CAP_S`). A vehicle that has sat
longer than that is stuck, not dwelling: the schedule expected it to have
left, and it is scored against the clock again. Without the cap, a train that
arrived five minutes late and then sat for an hour and a half read as five
minutes late throughout while the feed had it at an hour and forty. With it,
the count of ten-minute-plus disagreements at peak fell from 72 to 57, below
the 60 that clock scoring produces, and every gain of the hold stayed.

## Idle layovers

A vehicle waiting at its origin ahead of departure reads as exactly zero. That
says nothing about lateness, so the headline median and the analytics leave
those out and the headline counts them separately.

## Confidence

Observations are marked low confidence where the vehicle sits more than 150m
(`MAX_SNAP_ERROR_M`) from the shape it reports running, or where the result
exceeds three hours, typically indicating a mismatched service date. These are
retained but excluded from analytics by default. In-transit observations whose
interpolation ratio falls outside the leg are marked medium, as are
`first_stop` placements.

## Comparing with the feed

The feed's figure is derived from the prediction nearest in time to the
observation, within five minutes, for the same trip and stop sequence: predicted
departure for a layover, predicted arrival otherwise. Nearest rather than
newest, because a backfill would otherwise compare an early-trip position
against a prediction from the end of that trip. No prediction in the window
leaves the comparison null.

Correlation is reported but is a weak test. Both figures share the same
schedule baseline and vehicle position, and delays span several minutes, so an
r above 0.99 is nearly guaranteed. The divergence statistics are thinned to one
observation per vehicle per minute; consecutive 15s reports from one vehicle
are near-duplicates.
