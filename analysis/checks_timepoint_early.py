"""Early arrivals at scheduling timepoints only: unadjusted, within route, and route level, for the three criteria."""
import sys
import json
import numpy as np
import pandas as pd
import analyze as an
import checks as ck

a, w, kept = ck.setup(sys.argv[1])
U_all = an.Units(w, kept)
rflags_all, _ = ck.route_flags_for(w, U_all)
Ut = an.Units(w[w.timepoint == 1], kept)
route_ids = pd.factorize(Ut.u.route_id)[1]
rshare = pd.read_csv(sys.argv[2] + "/table_route_shares.csv", dtype={"route_id": str}).set_index("route_id")
rflags = {c: (rshare[c].reindex(route_ids).fillna(0) >= an.ROUTE_SHARE).to_numpy() for c in an.CRITERIA}
num, den = Ut.val["early"]
out = []
for crit in an.CRITERIA:
    pt = {"unadjusted": an.within_gap(Ut.cells["none"], Ut.flags[crit], num, den, np.ones(len(Ut.u)))[0],
          "within_route": an.within_gap(Ut.cells["route"], Ut.flags[crit], num, den, np.ones(len(Ut.u)))[0],
          "route_level": an.route_gap(Ut, rflags[crit], num, den, np.ones(len(Ut.u)))}
    dr = {k: [] for k in pt}
    for _ in range(500):
        ww = Ut.weights(True)
        dr["unadjusted"].append(an.within_gap(Ut.cells["none"], Ut.flags[crit], num, den, ww)[0])
        dr["within_route"].append(an.within_gap(Ut.cells["route"], Ut.flags[crit], num, den, ww)[0])
        dr["route_level"].append(an.route_gap(Ut, rflags[crit], num, den, ww))
    for k in pt:
        out.append(dict(criterion=crit, column=k, **ck.summarize(pt[k], dr[k])))
df = pd.DataFrame(out)
df.to_csv(sys.argv[2] + "/table_early_timepoints.csv", index=False)
df["est"] = df.apply(lambda r: f"{100*r.estimate:+.1f} ({100*r.ci_lo:+.1f}, {100*r.ci_hi:+.1f}) p={r.p_boot:.2f}", axis=1)
print(df.pivot(index="criterion", columns="column", values="est").to_string())
