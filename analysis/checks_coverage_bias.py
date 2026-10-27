"""How much uneven coverage biases the October comparisons, measured on September 28-30 timepoint events.

Three versions of each flagged-minus-unflagged gap, on the MBTA's mid-route timepoint departures:
  complete  - the MBTA's full record
  logged    - the MBTA's record, restricted to events our log also has (coverage effect alone)
  ours      - our own arrival log on those same events (coverage plus arrival-versus-departure)
Overall (arrival-weighted) and within route x direction cells; intervals resample routes.
"""
import numpy as np
import pandas as pd
import analyze as an

rng = np.random.default_rng(20261026)
DAYS = ["2026-09-28", "2026-09-29", "2026-09-30"]
m = pd.read_parquet("data/mbta_ad_sep28_30.parquet")
m["route_id"] = an.gtfs_route_id(m.route_id)
sch = pd.to_datetime(m.scheduled.str[11:19], format="%H:%M:%S"); m["tod"] = sch.dt.hour * 3600 + sch.dt.minute * 60 + sch.dt.second
act = pd.to_datetime(m.actual.str[11:19], format="%H:%M:%S", errors="coerce"); m["act_tod"] = act.dt.hour * 3600 + act.dt.minute * 60 + act.dt.second
m = m[(m.point_type == "Midpoint") & m.act_tod.notna()].copy()
m["mbta_late_s"] = m.act_tod + np.where(m.act_tod < m.tod - 6 * 3600, 86400, 0) - m.tod
a = pd.read_csv("data/arrivals_window1.csv.gz", usecols=["start_date", "route_id", "stop_id", "scheduled_time", "late_s"],
                dtype={"start_date": str, "route_id": str, "stop_id": str, "scheduled_time": str, "late_s": "float64"}, engine="pyarrow")
a = a[a.start_date.isin(DAYS)].copy()
st = pd.to_datetime(a.scheduled_time, utc=True).dt.tz_convert("America/New_York")
a["tod"] = (st - st.dt.normalize()).dt.total_seconds().astype(int)
a = a.drop_duplicates(["start_date", "route_id", "stop_id", "tod"], keep=False)
m = m.merge(a[["start_date", "route_id", "stop_id", "tod", "late_s"]], left_on=["service_date", "route_id", "stop_id", "tod"],
            right_on=["start_date", "route_id", "stop_id", "tod"], how="left")
m["logged"] = m.late_s.notna()
sb = pd.read_csv("data/stops_bg.csv", dtype={"stop_id": str}).set_index("stop_id")
m["route_dir"] = m.route_id + "|" + m.direction_id
routes = m.route_id.unique()


def gap(df, val, crit, within):
    f = df[crit].to_numpy(bool)
    if not within:
        return df.loc[f, val].mean() - df.loc[~f, val].mean()
    g = df.groupby(["route_dir", crit])[val].agg(["sum", "size"]).unstack(crit)
    g = g.dropna()
    if g.empty:
        return np.nan
    m1, m0 = g[("sum", True)] / g[("size", True)], g[("sum", False)] / g[("size", False)]
    w = g[("size", True)] * g[("size", False)] / (g[("size", True)] + g[("size", False)])
    return float((w * (m1 - m0)).sum() / w.sum())


rows = []
for crit in ["ej_income", "ej_minority"]:
    m[crit] = m.stop_id.map(sb[crit]).fillna(False).astype(bool)
    for meas, thr in [("late", 300), ("early", -60)]:
        m["v_mbta"] = (m.mbta_late_s > thr) if meas == "late" else (m.mbta_late_s < thr)
        m["v_ours"] = (m.late_s > thr) if meas == "late" else (m.late_s < thr)
        m["v_mbta"] = m.v_mbta.astype(float); m["v_ours"] = m.v_ours.astype(float)
        for version, df, val in [("complete", m, "v_mbta"), ("logged", m[m.logged], "v_mbta"), ("ours", m[m.logged], "v_ours")]:
            for within in [False, True]:
                pt = gap(df, val, crit, within)
                bs = []
                by_route = {r: g for r, g in df.groupby("route_id")}
                for _ in range(400):
                    pick = rng.choice(routes, len(routes))
                    bs.append(gap(pd.concat([by_route[r] for r in pick if r in by_route]), val, crit, within))
                rows.append(dict(criterion=crit, measure=meas, version=version, level="within route" if within else "overall",
                                 gap=100 * pt, lo=100 * np.nanpercentile(bs, 2.5), hi=100 * np.nanpercentile(bs, 97.5)))
out = pd.DataFrame(rows)
out.to_csv("output/window1_v2/table_coverage_bias.csv", index=False)
out["txt"] = out.apply(lambda r: f"{r.gap:+.1f} ({r.lo:+.1f}, {r.hi:+.1f})", axis=1)
print(out.pivot_table(index=["criterion", "measure", "level"], columns="version", values="txt", aggfunc="first")[["complete", "logged", "ours"]].to_string())
