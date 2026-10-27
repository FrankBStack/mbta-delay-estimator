"""September 28-30 against the MBTA's timepoint records: which events our arrival log misses, and which
trips the MBTA runs on the headway standard.

Writes data/trip_standard.csv (GTFS trip_id -> MBTA standard_type, from matched timepoint events).
"""
import numpy as np
import pandas as pd
import analyze as an

DAYS = ["2026-09-28", "2026-09-29", "2026-09-30"]
m = pd.read_parquet("data/mbta_ad_sep28_30.parquet")
m["route_id"] = an.gtfs_route_id(m.route_id)
sch = pd.to_datetime(m.scheduled.str[11:19], format="%H:%M:%S")
m["tod"] = sch.dt.hour * 3600 + sch.dt.minute * 60 + sch.dt.second
act = pd.to_datetime(m.actual.str[11:19], format="%H:%M:%S", errors="coerce")
m["act_tod"] = act.dt.hour * 3600 + act.dt.minute * 60 + act.dt.second
m = m[(m.point_type == "Midpoint") & m.act_tod.notna()].copy()
m["mbta_late"] = m.act_tod + np.where(m.act_tod < m.tod - 6 * 3600, 86400, 0) - m.tod

a = pd.read_csv("data/arrivals_window1.csv.gz", usecols=["start_date", "route_id", "trip_id", "stop_id", "scheduled_time"],
                dtype=str, engine="pyarrow")
a = a[a.start_date.isin(DAYS)].copy()
st = pd.to_datetime(a.scheduled_time, utc=True).dt.tz_convert("America/New_York")
a["tod"] = (st - st.dt.normalize()).dt.total_seconds().astype(int)
a = a.drop_duplicates(["start_date", "route_id", "stop_id", "tod"], keep=False)
j = m.merge(a[["start_date", "route_id", "stop_id", "tod", "trip_id"]], left_on=["service_date", "route_id", "stop_id", "tod"],
            right_on=["start_date", "route_id", "stop_id", "tod"], how="left")
j["matched"] = j.trip_id.notna()
j["early"] = j.mbta_late < -60

print("== 1. MBTA midpoint departures we have no arrival for")
print(j.groupby("matched").agg(events=("early", "size"), early_pct=("early", lambda x: round(100 * x.mean(), 1)),
                               late_pct=("mbta_late", lambda x: round(100 * (x > 300).mean(), 1))).to_string())

sb = pd.read_csv("data/stops_bg.csv", dtype={"stop_id": str}).set_index("stop_id")
j = j.join(sb[["ej_income", "ej_minority", "fta_minority"]], on="stop_id")
busy = j.groupby("stop_id").size()
j["stop_events"] = j.stop_id.map(busy)
j["busy_tercile"] = pd.qcut(j.stop_events.rank(method="first"), 3, labels=["quiet", "middle", "busy"])
for c in ["ej_income", "ej_minority", "fta_minority"]:
    g = j.groupby(j[c].fillna(False).astype(bool)).agg(events=("matched", "size"), unmatched_pct=("matched", lambda x: round(100 * (1 - x.mean()), 1)),
                                                      early_unmatched_pct=("early", lambda x: np.nan))
    early_by = j[~j.matched].groupby(j[c].fillna(False).astype(bool)).early.mean().mul(100).round(1)
    g["early_pct_among_unmatched"] = early_by
    print(f"\n{c}:"); print(g.drop(columns="early_unmatched_pct").to_string())
print("\nby how often the stop appears in the MBTA file:")
print(j.groupby("busy_tercile", observed=True).agg(unmatched_pct=("matched", lambda x: round(100 * (1 - x.mean()), 1)),
                                                     early_pct=("early", lambda x: round(100 * x.mean(), 1))).to_string())

# 2. trip -> standard type, from matched events (a GTFS weekday trip id repeats on every weekday of the rating)
ts = j[j.matched].groupby("trip_id").standard_type.agg(lambda s: s.mode().iat[0]).rename("standard_type")
ts.to_csv("data/trip_standard.csv")
print(f"\n== 2. trips with a standard type: {len(ts):,} ({ts.value_counts().to_dict()})")
