# Validation against the MBTA's predictions

How the position-derived delay estimator was validated against the MBTA's own
predictions, including the bugs the comparison caught. Headline figures are in the
main README; this is the full breakdown.

Since the MBTA publishes no delay field, its column here is derived as
predicted arrival minus scheduled arrival for the same trip and stop. The two
figures answer different questions (ours is how late a vehicle is right now,
theirs is how late it will be on arrival), so the interesting part is where and
why they diverge.

The September tables are measured after two corrections to the estimator;
the July tables at the end predate them and are kept because they document
how it was debugged. The first fixed the feed join (`with_feed` in `app/services/delay.py`), which
took the newest prediction for a stop rather than the contemporaneous one.
Re-measured after that over a weekday evening peak: correlation 0.9935, mean
divergence +19s, σ 50s, 88.8% within 60s (87,461 compared observations).

The second is the dwell hold: `stopped_at` now records the deviation at the
arrival event and holds it, rather than measuring against the clock. The
`stopped_at` row in the peak table below is the case it addresses. The +19s
mean divergence was mostly this: recomputing the same observations against
predicted arrival gave +34s, against predicted departure −17s, for both the
`stopped_at` and `interpolated` classes, which is what you get from comparing a
during-dwell clock reading against an at-arrival figure. `first_stop` is now
floored at zero like `layover`, which the −127s in the peak table called for,
and idle vehicles ahead of their origin (either method, delay 0) are excluded
from all aggregates.
The effect of the dwell hold and its cap, measured on identical observations,
is in the next section.

## The dwell hold, before and after

Measured on Wednesday, September 16, 2026 over the same two service windows as
the July tables below. Every column scores the same observations against the
same feed values; the only difference is the estimator. "Clock" re-derives the
pre-hold figure from each observation's stored scheduled time, so `stopped_at`
and `first_stop` rows read as the clock would have measured them. "Hold" is
the arrival deviation held through the dwell. "Capped" is the hold with the
five-minute cap described at the end of this section. (The like-for-like feed
pairing that landed with the hold applies to every column and cannot be undone
from stored data.)

Morning peak, 07:00–09:10. 80,809 observations after thinning, 80,535 with a
feed figure to compare against, 831 vehicles on 167 routes:

| Metric | Clock | Hold | Capped |
|---|---:|---:|---:|
| Mean divergence | +24s | +15s | +16s |
| Median divergence | +16s | +9s | +9s |
| p10 / p90 | −11s / +71s | −12s / +52s | −12s / +53s |
| Within 60s of feed | 85.0% | 90.0% | 90.0% |
| Within 120s of feed | 95.6% | 96.6% | 96.6% |
| Standard deviation | 67s | 82s | 63s |
| Correlation with feed | 0.9877 | 0.9813 | 0.9890 |
| More than 10 min from feed | 60 | 72 | 57 |

Overnight, 00:17–05:00. 14,111 observations, 14,032 compared, 358 vehicles on
108 routes:

| Metric | Clock | Hold | Capped |
|---|---:|---:|---:|
| Mean divergence | +16s | +8s | +12s |
| Median divergence | +10s | +7s | +7s |
| p10 / p90 | −12s / +52s | −12s / +42s | −12s / +43s |
| Within 60s of feed | 91.1% | 93.0% | 93.0% |
| Within 120s of feed | 97.5% | 98.1% | 98.1% |
| Standard deviation | 45s | 120s | 40s |
| Correlation with feed | 0.9952 | 0.9656 | 0.9962 |
| More than 10 min from feed | 1 | 22 | 0 |

By placement method at peak, mean absolute divergence:

| Method | Compared | Clock | Hold | Capped |
|---|---:|---:|---:|---:|
| `interpolated` | 45,901 | 39s | 39s | 39s |
| `stopped_at` | 32,116 | 30s | 11s | 10s |
| `layover` | 2,372 | 35s | 35s | 35s |
| `first_stop` | 146 | 208s | 34s | 34s |

The hold does what it was meant to: the `stopped_at` class, which is 40% of
peak observations, went from the worst-agreeing mid-route method to the best,
and the systematic offset in the headline mean roughly halved. The p90 moved by
19 seconds; the p10 did not move at all, which is what you'd expect from a
change that only affects vehicles reading late while they dwell.

### Where the hold made things worse

Under the plain hold, standard deviation and correlation both got worse, and
the reason is a small tail, not the bulk. At peak, 72 of 80,535 compared
observations diverge by more than ten minutes. Leaving those out, the standard
deviation is 49s under the hold against 67s by the clock, and 37s against 45s
overnight.

The tail splits two ways:

- 46 are `interpolated` and were outliers before the change too. They are
  vehicles reporting a trip whose schedule is nowhere near them, such as two
  Red Line trains reading 78 minutes early while the feed had them 21 minutes
  late. That is a trip assignment problem, below the three-hour cutoff that
  would have flagged it low confidence.
- 26 are `stopped_at`, of which 16 are new. All have the same shape: the
  vehicle arrived a few minutes late and then sat at the stop, for a median of
  19 minutes and up to 98. One Green Line C train arrived five minutes late
  and stayed for an hour and forty minutes; the hold reports it five minutes
  late while the clock and the feed both say an hour and forty-three.

The second group is a real limitation of the plain hold. It is correct for a
normal dwell of a minute or two, where the clock reading is an artifact of the
schedule having no dwell time, and wrong for a vehicle that is genuinely
stuck.

### The cap

The fix is a cap on how long the hold applies: once a vehicle has sat longer
than the cap, it is scored against the clock again. Three values were tried on
the same observations:

| Cap | Peak σ | Peak within 60s | Peak > 10 min | Overnight σ | Overnight > 10 min |
|---|---:|---:|---:|---:|---:|
| none (hold) | 82s | 90.0% | 72 | 120s | 22 |
| 3 min | 64s | 89.8% | 57 | 42s | 0 |
| 5 min | 63s | 90.0% | 57 | 40s | 0 |
| 10 min | 62s | 90.0% | 56 | 37s | 0 |

Three minutes begins to clip real dwells, visible as the within-60s share
dipping. Ten minutes buys one second of spread at the cost of a stuck vehicle
under-reading for ten minutes. Five minutes keeps every gain of the hold and
removes the tail it introduced, which is the "Capped" column in the tables
above. The 57 peak observations still more than ten minutes from the feed are
the trip-assignment cases in the first group, which no dwell rule can fix.

## The first-stop bug

This comparison caught a real bug in the first version of the estimator.
Broken down by placement method, mid-route stops agreed with the agency to
within 16 seconds, but vehicles stopped at the first stop of their trip came
out 323 seconds early on average while the feed reported them on time.

Both numbers made sense on their own terms. A bus sitting at its origin at
04:55 ahead of an 05:00 departure has technically arrived five minutes early,
but it isn't going to leave early, so the figure is useless.

Vehicles at their first stop are now measured against scheduled *departure*,
floored at zero. Mid-route stops keep the signed comparison, since a vehicle
passing a timepoint two minutes early really is early and passengers miss it.

Recomputed over the same observations with the same feed values, changing only
the estimator:

| Metric | Before | After |
|---|---|---|
| Correlation with feed | 0.851 | 0.985 |
| Mean divergence | −47s | +6s |
| Standard deviation | 166s | 45s |
| Within 60s of feed | 76.4% | 92.2% |

The layover class alone moved from −323s mean divergence to −8s.

## Agreement across service levels

Measured over a continuous run on Tuesday, July 28, 2026, split between overnight
service and the weekday morning peak:

| | Overnight (00:17–05:00) | Morning peak (07:00–09:10) |
|---|---:|---:|
| Observations | 13,126 | 7,751 |
| Distinct vehicles | 231 | 765 |
| Routes | 92 | 166 |
| Mean delay (computed) | 129s | 162s |
| Correlation with feed | 0.9916 | 0.9597 |
| Mean divergence | +11s | +23s |
| Standard deviation | 45s | 84s |
| Within 60s of feed | 92.9% | 87.1% |

Agreement is noticeably weaker at peak: service runs later on average and the
spread between the two methods roughly doubles. That's expected, since
congestion and boarding add variance that a position-derived figure and a
forward-looking prediction absorb differently.

The offset itself is systematic rather than noise. It was first read as
predictions baking in expected recovery; the later pairing analysis above
attributes most of it to comparing a dwelling vehicle against its recorded
arrival.

Breaking the peak window down by placement method shows where the spread is:

| Method | Observations | Mean divergence | Mean absolute divergence |
|---|---:|---:|---:|
| `interpolated` | 3,762 | +18s | 35s |
| `stopped_at` | 2,764 | +43s | 47s |
| `layover` | 1,209 | −1s | 3s |
| `first_stop` | 16 | −127s | 127s |

Most of it is `stopped_at`. While a vehicle sat at a stop, our figure kept
growing (it was measured against that stop's scheduled arrival and time kept
passing), while the agency had already recorded the arrival. Since the MBTA
schedules no dwell at all but a handful of stops, this made the figure sawtooth
by the dwell at every stop. It is now held at the arrival deviation; see above.

`layover` holds at 3s mean absolute divergence even at peak, which suggests the
departure-based rule is right.

Individual routes show the effect more sharply. At peak, route 504 measured
13m36s late by position against a 12m24s prediction; earlier, in an overnight
window, route 8 measured 8m42s late while the MBTA predicted arrival 1m18s
early, implying roughly ten minutes of expected recovery before its next
timepoint.

## Agreement by mode

The per-mode table in the README (Monday, September 28, 2026) shows commuter
rail agreeing with the feed far less often than the other modes: 67.9% within
60s against 91–95%. Divergence alone can't say which side is off, so both
figures were scored against actual arrivals (`arrival_score`, see
[operations.md](operations.md#arrival-scoring)): for each arrival, the error of
the MBTA's prediction and of the arrival our delay implied, at the moments the
countdown read 1, 2, 5, 10, 15 and 20 minutes. Error is estimate minus
actual, so negative means the train came later than the estimate said.
637,602 arrivals scored September 24–29, 2026, 9,510 of them commuter rail.
Scoring produced nothing from September 25 11:04 UTC to September 27 21:56
UTC while a pass was stalled, so this is about three and a half days of
data. Until September 30 the position estimate was paired with the nearest
observation within 45 seconds either side of the prediction, which at the
one- and two-minute horizons could be the arrival itself; those two rows
flatter the position column. From five minutes out the pairing could not
reach the arrival, and those figures stand.

| Minutes out | MBTA mean abs error | MBTA bias | Position mean abs error | Position bias |
|---:|---:|---:|---:|---:|
| 1 | 18s | −13s | 31s | +11s |
| 2 | 27s | −20s | 50s | +19s |
| 5 | 54s | −45s | 68s | +11s |
| 10 | 92s | −82s | 86s | −7s |
| 15 | 119s | −110s | 104s | −25s |
| 20 | 139s | −131s | 117s | −39s |

The MBTA's commuter rail predictions run optimistic, and more so the further
out. Ours is close to unbiased out to ten minutes. Because the site compares
the two at the same moment, the gap between the biases is what the divergence
measures: between stations, ours reads 55s later than the feed on average
(87,739 observations in the 24 hours to 1:30 PM on September 29), which is the
MBTA's −45s at five minutes less our +11s. Stopped trains agree 99% of the
time, layovers 97%; the whole disagreement is between stations.

The other modes show the same shape, only smaller, because their next stop is
always close:

| | 1 min: MBTA / position | 5 min | 10 min |
|---|---:|---:|---:|
| Subway | 11s (−8) / 28s (+13) | 35s (−27) / 45s (−3) | 62s (−52) / 59s (−23) |
| Commuter rail | 18s (−13) / 31s (+11) | 54s (−45) / 68s (+11) | 92s (−82) / 86s (−7) |
| Bus | 33s (−24) / 41s (−6) | 76s (−51) / 92s (−28) | 118s (−82) / 136s (−59) |

Mean absolute error, with bias in brackets. On every mode the feed is more
accurate inside five minutes and biased early; ours is noisier close in
(position placement and the poll interval) and less biased further out.

By line, agreement tracks station spacing. The 24 hours to 1:30 PM on September 29:

| Line | Compared | Mean divergence | Within 60s |
|---|---:|---:|---:|
| Needham | 4,454 | +33s | 81.8% |
| Fairmount | 5,920 | +34s | 80.0% |
| Newburyport/Rockport | 14,019 | +40s | 74.0% |
| Franklin/Foxboro | 8,381 | +40s | 73.0% |
| Fitchburg | 11,948 | +40s | 70.3% |
| Haverhill | 8,647 | +43s | 70.0% |
| Lowell | 6,884 | +38s | 64.0% |
| Framingham/Worcester | 12,476 | +61s | 63.3% |
| Providence/Stoughton | 13,983 | +52s | 62.8% |
| Greenbush | 5,037 | +52s | 59.6% |
| Kingston | 5,542 | +52s | 57.4% |
| Fall River/New Bedford | 13,563 | +50s | 55.2% |

Nothing here points at an estimator rule to change. The short-horizon noise
is placement and polling, not a systematic error, and the between-station gap
is the feed's.
