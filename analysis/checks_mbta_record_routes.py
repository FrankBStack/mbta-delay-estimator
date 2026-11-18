"""Exploratory: route against route in the MBTA's timepoint record. Each route's share of mid-route timepoint
departures more than 5 min late, flagged routes minus unflagged routes, each route counted once (as analyze.route_gap).
Route flags are those of analyze.py (table_route_shares.csv). Intervals resample days and routes together.

Usage: python checks_mbta_record_routes.py <zip> 2026-09 2026-09-08 [last day] [days to skip ...]
"""
import sys
import zipfile
import numpy as np
import pandas as pd
import analyze as an

zpath, month, first = sys.argv[1], sys.argv[2], sys.argv[3]
last, skip = (sys.argv[4], sys.argv[5:]) if len(sys.argv) > 4 else ("2100-01-01", [])
rng = np.random.default_rng(20261118)
z = zipfile.ZipFile(zpath)
m = pd.read_csv(z.open(f"MBTA_Bus_Arrival_Departure_Times_2026/MBTA-Bus-Arrival-Departure-Times_{month}.csv"),
                usecols=["service_date", "route_id", "stop_id", "point_type", "scheduled", "actual"], dtype=str, engine="pyarrow")
d = pd.to_datetime(m.service_date)
m = m[(d >= first) & (d <= last) & ~d.isin(pd.to_datetime(skip)) & (d.dt.dayofweek < 5) & (m.point_type == "Midpoint") & m.actual.notna()].copy()
sch = pd.to_datetime(m.scheduled.str[11:19], format="%H:%M:%S"); tod = sch.dt.hour * 3600 + sch.dt.minute * 60 + sch.dt.second
act = pd.to_datetime(m.actual.str[11:19], format="%H:%M:%S"); atod = act.dt.hour * 3600 + act.dt.minute * 60 + act.dt.second
m["late"] = ((atod + np.where(atod < tod - 6 * 3600, 86400, 0) - tod) > 300).astype(float)

shares = pd.read_csv("output/window1_v2/table_route_shares.csv", dtype={"route_id": str}).set_index("route_id")
m["gtfs_route"] = an.gtfs_route_id(m.route_id)
known = m.gtfs_route.isin(shares.index)
print(f"{month}: {m.service_date.nunique()} weekdays, {len(m):,} mid-route timepoint departures, "
      f"{(~known).sum():,} on {m.gtfs_route[~known].nunique()} routes without a flag left out")
m = m[known]
day = pd.factorize(m.service_date)[0]
route, route_ids = pd.factorize(m.gtfs_route)
nd, nr = day.max() + 1, len(route_ids)
late = m.late.to_numpy()


def gap(flag, dw, rw):
    A = np.bincount(route, weights=dw, minlength=nr)
    S = np.bincount(route, weights=dw * late, minlength=nr)
    ok = (A > 0) & (rw > 0)
    share = np.where(ok, S / np.maximum(A, 1e-12), np.nan)
    a1, a0 = ok & flag, ok & ~flag
    return np.average(share[a1], weights=rw[a1]) - np.average(share[a0], weights=rw[a0])


rows = []
for crit in an.CRITERIA:
    flag = (shares[crit].reindex(route_ids) >= an.ROUTE_SHARE).to_numpy()
    pt = gap(flag, np.ones(len(m)), np.ones(nr))
    draws = [gap(flag, np.bincount(rng.integers(0, nd, nd), minlength=nd)[day].astype(float),
                 np.bincount(rng.integers(0, nr, nr), minlength=nr).astype(float)) for _ in range(an.REPS)]
    rows.append(dict(criterion=crit, flagged_routes=int(flag.sum()), unflagged_routes=int((~flag).sum()), gap=100 * pt,
                     lo=100 * np.percentile(draws, 2.5), hi=100 * np.percentile(draws, 97.5)))
out = pd.DataFrame(rows)
out.to_csv(f"output/window1_v2/table_mbta_record_routes_{month}.csv", index=False)
print(out.to_string(index=False, float_format=lambda x: f"{x:+.1f}"))
