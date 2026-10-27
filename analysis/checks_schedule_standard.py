"""Exploratory: lateness gaps on trips the MBTA judges by timetable (schedule standard) only.

Default: trips matched to the MBTA's September 28-30 records (Friday trips have their own ids and are
missed). --rule: every trip classified by the November rule (make_standard_rule.py), keyed on the trip's
first scheduled hour.
"""
import sys
import zipfile
import numpy as np
import pandas as pd
import analyze as an
import checks as ck


def rule_standard(trip_ids):
    st = pd.read_csv(zipfile.ZipFile(an.D + "MBTA_GTFS.zip").open("stop_times.txt"), dtype=str,
                     usecols=["trip_id", "stop_sequence", "departure_time"])
    st = st[st.trip_id.isin(set(trip_ids))]
    first = st.loc[st.stop_sequence.astype(int).groupby(st.trip_id).idxmin()]
    t = first.assign(hour=first.departure_time.str[:2].astype(int) % 24)[["trip_id", "hour"]]
    t = t.merge(pd.read_csv(an.D + "trips_bus.csv", dtype=str)[["trip_id", "route_id", "direction_id"]], on="trip_id")
    t["direction_id"] = t.direction_id.astype(int)
    cell = pd.read_csv(an.D + "standard_rule.csv", dtype={"route_id": str})
    rd = pd.read_csv(an.D + "standard_rule_route_direction.csv", dtype={"route_id": str})
    rt = pd.read_csv(an.D + "standard_rule_route.csv", dtype={"route_id": str})
    for x in (cell, rd, rt):
        x["route_id"] = an.gtfs_route_id(x.route_id)
    t = t.merge(cell, on=["route_id", "direction_id", "hour"], how="left")
    t = t.merge(rd, on=["route_id", "direction_id"], how="left").merge(rt, on="route_id", how="left")
    s = t.standard.fillna(t.rd_standard).fillna(t.route_standard).fillna("Schedule")
    return s.set_axis(t.trip_id)


a, w, kept = ck.setup(sys.argv[1])
if "--rule" in sys.argv:
    w["std"] = w.trip_id.map(rule_standard(w.trip_id.unique()))
else:
    w["std"] = w.trip_id.map(pd.read_csv(an.D + "trip_standard.csv", dtype=str).set_index("trip_id").standard_type)
print("weekday arrivals by standard:", w["std"].value_counts(dropna=False, normalize=True).round(3).to_dict())
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
