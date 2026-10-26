"""Holding or running early? Early arrivals at timepoints against the stop right after each timepoint.

A bus that reaches a timepoint early and holds there is roughly on time at the next stop; one that leaves
early is early there too.
"""
import sys
import numpy as np
import pandas as pd
import analyze as an
import checks as ck

a, w, kept = ck.setup(sys.argv[1])
tp = pd.read_csv(an.D + "timepoints.csv", dtype={"trip_id": str, "stop_sequence": "float64", "timepoint": "float64"})
tp = tp.sort_values(["trip_id", "stop_sequence"])
tp["prev_is_timepoint"] = tp.groupby("trip_id").timepoint.shift(1).fillna(0) == 1
nxt = tp[tp.prev_is_timepoint & (tp.timepoint == 0)][["trip_id", "stop_sequence"]].assign(after_timepoint=True)
w = w.merge(nxt, on=["trip_id", "stop_sequence"], how="left")
w["after_timepoint"] = w.after_timepoint.fillna(False).astype(bool)
w["kind"] = np.where(w.timepoint == 1, "timepoint", np.where(w.after_timepoint, "stop after timepoint", "other"))
print(w.groupby("kind").agg(arrivals=("early", "size"), early_pct=("early", lambda x: round(100 * x.mean(), 1)),
                            late_pct=("late", lambda x: round(100 * x.mean(), 1))).to_string())
print("\nroutes 15, 23, 66:")
print(w[w.route_id.isin(["15", "23", "66"])].groupby(["route_id", "kind"]).early.agg(
    early_pct=lambda x: round(100 * x.mean(), 1), arrivals="size").to_string())
for label, sub in [("timepoints", w[w.timepoint == 1]), ("stops after timepoints", w[w.after_timepoint])]:
    U = an.Units(sub, kept)
    num, den = U.val["early"]
    pt = {lv: an.within_gap(U.cells[lv], U.flags["ej_income"], num, den, np.ones(len(U.u)))[0] for lv in ["none", "route"]}
    dr = {lv: [an.within_gap(U.cells[lv], U.flags["ej_income"], num, den, U.weights(True))[0] for _ in range(500)] for lv in pt}
    for lv in pt:
        s = ck.summarize(pt[lv], dr[lv])
        print(f"{label:24s} income early-arrival gap, {lv:6s}: {100*s['estimate']:+.1f} pts ({100*s['ci_lo']:+.1f}, {100*s['ci_hi']:+.1f}) p={s['p_boot']:.2f}")
