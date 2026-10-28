"""Exploratory: flagged-minus-unflagged gaps in the MBTA's complete timepoint record, over every weekday of a
month's file (no dependence on our log). Late = departure more than 5 min after schedule; early = more than
60 s before. Overall and within route x direction; intervals resample days and routes together.

Usage: python checks_mbta_record_gaps.py 2026-09 2026-09-08 [last day] [days to skip ...]
"""
import sys
import zipfile
import numpy as np
import pandas as pd

month, first = sys.argv[1], sys.argv[2]
last, skip = (sys.argv[3], sys.argv[4:]) if len(sys.argv) > 3 else ("2100-01-01", [])
rng = np.random.default_rng(20261026)
z = zipfile.ZipFile("data/MBTA_Bus_Arrival_Departure_Times_2026.zip")
m = pd.read_csv(z.open(f"MBTA_Bus_Arrival_Departure_Times_2026/MBTA-Bus-Arrival-Departure-Times_{month}.csv"),
                usecols=["service_date", "route_id", "direction_id", "stop_id", "point_type", "standard_type", "scheduled", "actual"],
                dtype=str, engine="pyarrow")
d = pd.to_datetime(m.service_date)
m = m[(d >= first) & (d <= last) & ~d.isin(pd.to_datetime(skip)) & (d.dt.dayofweek < 5) & (m.point_type == "Midpoint") & m.actual.notna()].copy()
sch = pd.to_datetime(m.scheduled.str[11:19], format="%H:%M:%S"); tod = sch.dt.hour * 3600 + sch.dt.minute * 60 + sch.dt.second
act = pd.to_datetime(m.actual.str[11:19], format="%H:%M:%S"); atod = act.dt.hour * 3600 + act.dt.minute * 60 + act.dt.second
dev = atod + np.where(atod < tod - 6 * 3600, 86400, 0) - tod
m["late"], m["early"] = (dev > 300).astype(float), (dev < -60).astype(float)
sb = pd.read_csv("data/stops_bg.csv", dtype={"stop_id": str}).set_index("stop_id")
day = pd.factorize(m.service_date)[0]; route = pd.factorize(m.route_id)[0]
cell = pd.factorize(m.route_id + "|" + m.direction_id)[0]
nd, nr = day.max() + 1, route.max() + 1


def gaps(f, v, w, cells):
    out = []
    for c in cells:
        nc = c.max() + 1
        idx = c * 2 + f
        A = np.bincount(idx, weights=w, minlength=2 * nc).reshape(nc, 2)
        S = np.bincount(idx, weights=w * v, minlength=2 * nc).reshape(nc, 2)
        ok = (A[:, 0] > 0) & (A[:, 1] > 0)
        g = S[ok, 1] / A[ok, 1] - S[ok, 0] / A[ok, 0]
        wt = A[ok, 0] * A[ok, 1] / (A[ok, 0] + A[ok, 1])
        out.append((wt * g).sum() / wt.sum())
    return out


rows = []
for subset, mask in [("all trips", np.ones(len(m), bool)), ("timetable-run trips", (m.standard_type == "Schedule").to_numpy())]:
    for crit in ["ej_income", "ej_minority", "fta_minority"]:
        f = m.stop_id.map(sb[crit]).fillna(False).astype(bool).to_numpy().astype(int)
        for meas in ["late", "early"]:
            v = m[meas].to_numpy()
            cells = [np.zeros(len(m), int)[mask], cell[mask]]
            pt = gaps(f[mask], v[mask], np.ones(mask.sum()), cells)
            draws = []
            for _ in range(500):
                w = (np.bincount(rng.integers(0, nd, nd), minlength=nd)[day] * np.bincount(rng.integers(0, nr, nr), minlength=nr)[route])[mask]
                draws.append(gaps(f[mask], v[mask], w.astype(float), cells))
            draws = np.array(draws)
            for i, lv in enumerate(["overall", "within route"]):
                rows.append(dict(subset=subset, criterion=crit, measure=meas, level=lv, gap=100 * pt[i],
                                 lo=100 * np.percentile(draws[:, i], 2.5), hi=100 * np.percentile(draws[:, i], 97.5)))
out = pd.DataFrame(rows)
out.to_csv(f"output/window1_v2/table_mbta_record_gaps_{month}.csv", index=False)
print(f"{month}: {m.service_date.nunique()} weekdays, {len(m):,} mid-route timepoint departures")
out["txt"] = out.apply(lambda r: f"{r.gap:+.1f} ({r.lo:+.1f}, {r.hi:+.1f})", axis=1)
print(out.pivot_table(index=["subset", "criterion", "level"], columns="measure", values="txt", aggfunc="first").to_string())
