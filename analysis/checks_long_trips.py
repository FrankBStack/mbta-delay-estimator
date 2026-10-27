"""Exploratory: arrivals more than an hour into a trip, where both early and late shares are high."""
import sys
import zipfile
import pandas as pd
import analyze as an

a = an.load(sys.argv[1])
w = a[a.day_type == "weekday"]
z = zipfile.ZipFile(an.D + "MBTA_GTFS.zip")
st = pd.read_csv(z.open("stop_times.txt"), dtype={"trip_id": str}, usecols=["trip_id", "stop_sequence"])
st["last3"] = st.groupby("trip_id").stop_sequence.rank(ascending=False) <= 3

b = w[w.sched_s_from_origin >= 3600].merge(st, on=["trip_id", "stop_sequence"], how="left")
mid = w[(w.sched_s_from_origin >= 1800) & (w.sched_s_from_origin < 2700)]
print(f"arrivals 60+ min: {len(b):,} ({100 * len(b) / len(w):.1f}% of weekday arrivals) on {b.route_id.nunique()} routes")
print(f"on time (neither late nor early): 60+ {1 - b.late.mean() - b.early.mean():.3f}, 30-45 {1 - mid.late.mean() - mid.early.mean():.3f}")
for k, g in b.groupby("last3"):
    print(f"last three stops of the trip = {k}: share {len(g) / len(b):.2f}, early {g.early.mean():.3f}, late {g.late.mean():.3f}")
r = b.groupby("route_id").agg(n=("late", "size"), late=("late", "mean"), early=("early", "mean")).sort_values("n", ascending=False)
r["share"] = r.n / len(b)
print(r.head(10).round(3).to_string())
print(f"top five routes: {r.share.head(5).sum():.2f} of arrivals")

ts = pd.read_csv(an.D + "trip_standard.csv", dtype=str).set_index("trip_id").standard_type
print("weekday arrivals by MBTA standard:", w.trip_id.map(ts).value_counts(dropna=False, normalize=True).round(3).to_dict())
