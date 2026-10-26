"""Exploratory: lateness gaps on trips the MBTA judges by timetable (schedule standard) only."""
import sys
import numpy as np
import pandas as pd
import analyze as an
import checks as ck

a, w, kept = ck.setup(sys.argv[1])
ts = pd.read_csv(an.D + "trip_standard.csv", dtype=str).set_index("trip_id").standard_type
w["std"] = w.trip_id.map(ts)
sub = w[w["std"] == "Schedule"]
print(f"schedule-standard arrivals: {len(sub):,} of {len(w):,}")
U = an.Units(sub, kept)
for crit in ["ej_income", "ej_minority", "fta_minority"]:
    for m in ["late", "early"]:
        num, den = U.val[m]
        for lv in ["none", "route_position"]:
            pt = an.within_gap(U.cells[lv], U.flags[crit], num, den, np.ones(len(U.u)))
            dr = [an.within_gap(U.cells[lv], U.flags[crit], num, den, U.weights(True))[0] for _ in range(300)]
            s = ck.summarize(pt[0], dr)
            print(f"{crit:13s} {m:5s} {lv:15s} {100*s['estimate']:+.1f} pts ({100*s['ci_lo']:+.1f}, {100*s['ci_hi']:+.1f})  mixed {pt[1]:.2f}")
