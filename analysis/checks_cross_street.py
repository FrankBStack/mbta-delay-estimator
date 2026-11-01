"""Robustness: stops whose opposite-direction twin across the street falls in a block group with the other flag.

Reports, for each criterion, the share of flagged stops with an unflagged stop within 50 m (and the reverse), then the
within route x direction x position gaps with those pairs dropped, both members flagged, or both unflagged.
Point estimates only, on weekday arrivals at stops with MIN_N or more.

Usage: python checks_cross_street.py data/arrivals_window1.csv.gz
"""
import sys
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
import analyze as an

PAIR_M = 50
a = an.load(sys.argv[1])
w = a[a.day_type == "weekday"]
sb = pd.read_csv(an.D + "stops_bg.csv", dtype={"stop_id": str}).set_index("stop_id")
stops = an.stop_attributes(sb)
n = w.groupby("stop_id").size()
stops = stops[stops.index.isin(n[n >= an.MIN_N].index)].copy()
U = an.Units(w, stops)
ones = U.weights(False)


def gaps(flag):
    f = flag.reindex(U.u.stop_id).to_numpy(float)
    keep = ~np.isnan(f)
    out = []
    for m in ["late", "error"]:
        num, den = U.val[m]
        gap, _ = an.within_gap(pd.factorize(U.cells["route_position"][keep])[0], f[keep].astype(bool), num[keep], den[keep], ones[keep])
        out.append(f"{m} {100 * gap if m == 'late' else gap:+.2f}")
    return "  ".join(out)


xy = stops[["x", "y"]].to_numpy()
for crit in an.CRITERIA:
    fl = stops[crit].to_numpy(bool)
    f, u = np.where(fl)[0], np.where(~fl)[0]
    df, _ = cKDTree(xy[u]).query(xy[f])
    du, _ = cKDTree(xy[f]).query(xy[u])
    near_f, near_u = f[df < PAIR_M], u[du < PAIR_M]
    print(f"{crit}: {100 * len(near_f) / len(f):.1f}% of {len(f)} flagged stops have an unflagged stop within {PAIR_M} m; "
          f"{100 * len(near_u) / len(u):.1f}% of {len(u)} unflagged have a flagged one")
    base = pd.Series(fl.astype(float), index=stops.index)
    drop, both_f, both_u = base.copy(), base.copy(), base.copy()
    drop.iloc[np.r_[near_f, near_u]] = np.nan
    both_f.iloc[near_u] = 1.0
    both_u.iloc[near_f] = 0.0
    for name, flag in [("as analyzed", base), ("pairs dropped", drop), ("pairs flagged", both_f), ("pairs unflagged", both_u)]:
        print(f"   {name:16s} {gaps(flag)}")
