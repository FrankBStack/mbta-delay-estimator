"""How many routes drive the unadjusted early-arrival gap: drop one route at a time and recompute."""
import sys
import numpy as np
import pandas as pd
import analyze as an
import checks as ck

a, w, kept = ck.setup(sys.argv[1])
routes = pd.read_csv(an.D + "routes.csv", dtype={"route_id": str}).set_index("route_id").route_short_name
for label, sub in [("all arrivals", w), ("timepoints only", w[w.timepoint == 1])]:
    U = an.Units(sub, kept)
    num, den = U.val["early"]
    g = U.flags["ej_income"]
    base = an.within_gap(U.cells["none"], g, num, den, np.ones(len(U.u)))[0]
    rid = pd.factorize(U.u.route_id)[1]
    rows = []
    for i, r in enumerate(rid):
        keep = (U.route != i).astype(float)
        rows.append((r, an.within_gap(U.cells["none"], g, num, den, keep)[0]))
    d = pd.DataFrame(rows, columns=["route_id", "gap_without"]).assign(change=lambda x: x.gap_without - base)
    d["route"] = d.route_id.map(routes).fillna(d.route_id)
    d = d.sort_values("change")
    print(f"\n== {label}: income early-arrival gap {100*base:+.2f} pts")
    print("routes whose removal lowers it most:")
    print(d.head(6).assign(gap_without=lambda x: (100*x.gap_without).round(2), change=lambda x: (100*x.change).round(2))[["route","gap_without","change"]].to_string(index=False))
    # cumulative: drop the top k contributors
    order = d.route_id.tolist()
    for k in [1, 2, 3, 5, 10]:
        drop = set(order[:k])
        keepw = (~pd.Series(U.u.route_id).isin(drop)).to_numpy().astype(float)
        print(f"  without top {k:2d}: {100*an.within_gap(U.cells['none'], g, num, den, keepw)[0]:+.2f} pts")
    # early share by route on income-flagged vs other stops, for the top routes
    top = d.head(3).route_id.tolist()
    s = sub[sub.route_id.isin(top)].join(kept.ej_income, on="stop_id").dropna(subset=["ej_income"])
    print(s.groupby(["route_id", "ej_income"]).early.agg(["mean", "size"]).assign(mean=lambda x: (100*x["mean"]).round(1)).to_string())
