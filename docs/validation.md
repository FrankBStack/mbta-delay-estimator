# Validation against the MBTA's predictions

How the position-derived delay estimator was validated against the MBTA's own
predictions, including a bug the comparison caught. Headline figures are in the
main README; this is the full breakdown.

Since the MBTA publishes no delay field, its column here is derived as
predicted arrival minus scheduled arrival for the same trip and stop. The two
figures answer different questions (ours is how late a vehicle is right now,
theirs is how late it will be on arrival), so the interesting part is where and
why they diverge.

The tables below predate a correction to the feed join (`with_feed` in
`app/services/delay.py`), which took the newest prediction for a stop rather
than the contemporaneous one, so treat their exact figures as approximate;
they're kept because they document how the estimator was debugged. Re-measured
after the correction over a weekday evening peak: correlation 0.9935, mean
divergence +19s, σ 50s, 88.8% within 60s (87,461 compared observations).

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

Measured over a continuous run on Tuesday 28 July 2026, split between overnight
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

The offset itself is systematic rather than noise: predictions bake in expected
recovery (schedule padding, time made up on an express segment), so the
position-derived figure reads consistently later.

Breaking the peak window down by placement method shows where the spread is:

| Method | Observations | Mean divergence | Mean absolute divergence |
|---|---:|---:|---:|
| `interpolated` | 3,762 | +18s | 35s |
| `stopped_at` | 2,764 | +43s | 47s |
| `layover` | 1,209 | −1s | 3s |
| `first_stop` | 16 | −127s | 127s |

Most of it is `stopped_at`. While a vehicle sits at a stop, our figure keeps
growing (it's measured against that stop's scheduled arrival and time keeps
passing), while the agency has already recorded the arrival and moved its
prediction to the next stop. Long peak dwells widen the gap, but it follows
from the two definitions rather than being a bug.

`layover` holds at 3s mean absolute divergence even at peak, which suggests the
departure-based rule is right.

Individual routes show the effect more sharply. At peak, route 504 measured
13m36s late by position against a 12m24s prediction; earlier, in an overnight
window, route 8 measured 8m42s late while the MBTA predicted arrival 1m18s
early, implying roughly ten minutes of expected recovery before its next
timepoint.
