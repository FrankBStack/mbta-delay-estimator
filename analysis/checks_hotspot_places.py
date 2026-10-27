"""Exploratory: where the adjusted hot spots are, grouped into places, and what they share."""
import sys
import zipfile
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
import analyze as an

OUT = "output/window1_v2/"

a = an.load(sys.argv[1])
w = a[a.day_type == "weekday"]
z = zipfile.ZipFile(an.D + "MBTA_GTFS.zip")
gs = pd.read_csv(z.open("stops.txt"), dtype=str, usecols=["stop_id", "municipality"])
st = pd.read_csv(z.open("stop_times.txt"), dtype={"trip_id": str, "stop_id": str},
                 usecols=["trip_id", "stop_id", "stop_sequence"])
st = st[st.trip_id.isin(pd.read_csv(an.D + "trips_bus.csv", dtype=str).trip_id)]
by_trip = st.groupby("trip_id").stop_sequence
terminals = set(st.loc[by_trip.idxmin(), "stop_id"]) | set(st.loc[by_trip.idxmax(), "stop_id"])

# coverage: logged arrivals over scheduled visits (origin excluded) on the trips the log observed
seen = w[["start_date", "trip_id"]].drop_duplicates()
visits = seen.merge(st[st.stop_sequence > st.groupby("trip_id").stop_sequence.transform("min")], on="trip_id")
coverage = w.groupby("stop_id").size() / visits.groupby("stop_id").size()

h = pd.read_csv(OUT + "hotspots.csv")
sm = pd.read_csv(OUT + "table_stop_measures.csv", dtype={"stop_id": str})
assert (h.stop_name.values == sm.stop_name.values).all()
h["stop_id"] = sm.stop_id.values
h["pos_min"] = sm.pos_min_mean.values
h = h.merge(gs, on="stop_id", how="left")
allstops = pd.read_csv(an.D + "stops_bg.csv", dtype={"stop_id": str})
h["d_terminal_m"] = cKDTree(allstops[allstops.stop_id.isin(terminals)][["x", "y"]].to_numpy()).query(h[["x", "y"]].to_numpy())[0]
h["coverage"] = h.stop_id.map(coverage)

flags = ["ej_income", "ej_minority", "fta_minority"]
rows, hot = [], {}
for measure, col in [("late", "late_r_class"), ("error", "err_r_class")]:
    s = h[h[col] == "hot"].copy()
    pairs = cKDTree(s[["x", "y"]].to_numpy()).query_pairs(an.BAND_M, output_type="ndarray")
    adj = sp.coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(s), len(s)))
    s["place"] = connected_components(adj, directed=False)[1]
    places = s.groupby("place").agg(
        stops=("n", "size"), arrivals=("n", "sum"),
        municipality=("municipality", lambda x: "/".join(sorted(set(x.dropna())))),
        routes=("main_route", lambda x: "/".join(sorted(set(map(str, x))))),
        **{f: (f, "mean") for f in flags}, example=("stop_name", "first"),
    ).sort_values(["stops", "arrivals"], ascending=False)
    places.insert(0, "measure", measure)
    rows.append(places)
    hot[measure] = s
    print(f"\n{measure}: {len(s)} hot stops in {len(places)} places")
    print(places.round(2).to_string(index=False))
    for f in flags:
        print(f"  {f}: stops {s[f].mean():.2f}, places with half or more flagged {(places[f] >= 0.5).mean():.2f}, all stops {h[f].mean():.2f}")
    for c in ["pos_min", "d_terminal_m", "coverage"]:
        print(f"  median {c}: hot {s[c].median():.2f}, all stops {h[c].median():.2f}")
pd.concat(rows).round(3).to_csv(OUT + "table_hotspot_places.csv", index=False)

# hot stops against the same routes at the same trip positions elsewhere, weighted by the hot stops' arrivals
w = w.assign(cell=w.route_id + "|" + w.direction_id.astype(str) + "|" + w.pos_bin.astype(str),
             later=(w.feed_300 < 0).astype(float).where(w.feed_300.notna()))
cols = ["feed_300", "later", "early", "late"]


def versus_elsewhere(stops):
    inn = w[w.stop_id.isin(stops)]
    ref = w[~w.stop_id.isin(stops)].groupby("cell")[cols].mean()
    share = inn.cell.value_counts(normalize=True)
    return pd.DataFrame({"here": inn[cols].mean(), "elsewhere": ref.reindex(share.index).mul(share, axis=0).sum()})


print("\nshared stops:", sorted(set(hot["late"].stop_name[hot["late"].stop_id.isin(hot["error"].stop_id)])))
e = hot["error"]
ref = w[~w.stop_id.isin(e.stop_id)].groupby("cell").feed_300.mean()
per_stop = w[w.stop_id.isin(e.stop_id)].groupby("stop_id").apply(lambda g: g.feed_300.mean() < ref.reindex(g.cell).mean())
print(f"prediction hot spots where buses came later than predicted by more than elsewhere: {per_stop.mean():.2f}")
print("all prediction hot spots\n", versus_elsewhere(e.stop_id).round(3))
for p in e.groupby("place").size().sort_values(ascending=False).index[:2]:
    print("prediction place", sorted(set(e[e.place == p].main_route.astype(str))), "\n", versus_elsewhere(e[e.place == p].stop_id).round(3))
lynn = hot["late"][hot["late"].stop_name.str.startswith("Western Ave")]
print("Lynn lateness hot spots\n", versus_elsewhere(lynn.stop_id).round(3))
nw = hot["late"][hot["late"].main_route.astype(str) == "505"]
print("route 505 cluster by direction:", w[w.stop_id.isin(nw.stop_id)].groupby("direction_id").stop_id.nunique().to_dict())
