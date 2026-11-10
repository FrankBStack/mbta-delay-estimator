"""November replication: H4 (early departures on timetable-run trips), H5 (long gaps on headway-run trips),
their within route x direction x position versions H4b and H5b, and coverage by area, as fixed in README.md.

A bus's time at a stop is its departure (`departed_at`) or, for a pass, the pass time. Each trip takes the
MBTA's majority September standard for its route, direction and first scheduled hour (make_standard_rule.py).
Scheduled visits come from the MBTA timetable version in effect each day (fetch_gtfs_archive.py).

Usage: python november.py data/visits_window2.csv.gz output/window2 2026-10-26 2026-11-20 2026-11-11
"""
import pathlib
import sys
import zipfile
import numpy as np
import pandas as pd
import analyze as an

EARLY_DEP_S, LONG_GAP, REPS = -60, 1.5, 1000
ARCHIVE = an.D + "gtfs_archive/"
rng = np.random.default_rng(20261110)


def weekdays(first, last, skip):
    d = pd.bdate_range(first, last)
    return d[~d.isin(pd.to_datetime(skip))]


def scheduled_visits(dates):
    """Every scheduled bus stop visit on each date, from the timetable version in effect that day."""
    feeds = pd.read_csv(ARCHIVE + "archived_feeds.txt", dtype=str)
    out = []
    for version, ds in pd.Series(dates).groupby(lambda i: feeds[(feeds.feed_start_date <= dates[i].strftime("%Y%m%d"))
                                                               & (feeds.feed_end_date >= dates[i].strftime("%Y%m%d"))]
                                                 .feed_start_date.iloc[0]):
        z = zipfile.ZipFile(f"{ARCHIVE}{version}.zip")
        bus = pd.read_csv(z.open("routes.txt"), dtype=str).query("route_type == '3'").route_id
        trips = pd.read_csv(z.open("trips.txt"), dtype=str, usecols=["route_id", "service_id", "trip_id", "direction_id"])
        trips = trips[trips.route_id.isin(bus)]
        cal = pd.read_csv(z.open("calendar.txt"), dtype=str)
        cd = pd.read_csv(z.open("calendar_dates.txt"), dtype=str)
        st = pd.read_csv(z.open("stop_times.txt"), dtype=str, usecols=["trip_id", "stop_sequence", "stop_id", "departure_time"])
        st = st[st.trip_id.isin(trips.trip_id)].dropna(subset=["departure_time"])
        hms = st.departure_time.str.split(":", expand=True).astype(int)
        st = st.assign(stop_sequence=st.stop_sequence.astype(int), dep_s=hms[0] * 3600 + hms[1] * 60 + hms[2]).drop(columns="departure_time")
        seq = st.groupby("trip_id").stop_sequence
        st["end"] = (st.stop_sequence == seq.transform("min")) | (st.stop_sequence == seq.transform("max"))
        st = st.merge(trips, on="trip_id")
        for d in ds:
            ymd, dow = d.strftime("%Y%m%d"), d.strftime("%A").lower()
            on = set(cal[(cal.start_date <= ymd) & (cal.end_date >= ymd) & (cal[dow] == "1")].service_id)
            on |= set(cd[(cd.date == ymd) & (cd.exception_type == "1")].service_id)
            on -= set(cd[(cd.date == ymd) & (cd.exception_type == "2")].service_id)
            out.append(st[st.service_id.isin(on)].drop(columns="service_id").assign(start_date=d.strftime("%Y-%m-%d")))
    s = pd.concat(out, ignore_index=True)
    s["direction_id"] = s.direction_id.astype(int)
    return s


def standards(sched):
    first = sched.loc[sched.groupby(["start_date", "trip_id"]).stop_sequence.idxmin(), ["trip_id", "route_id", "direction_id", "dep_s"]]
    t = first.drop_duplicates("trip_id").assign(hour=lambda x: (x.dep_s // 3600) % 24)
    rule = [pd.read_csv(an.D + f, dtype={"route_id": str}) for f in
            ["standard_rule.csv", "standard_rule_route_direction.csv", "standard_rule_route.csv"]]
    for r in rule:
        r["route_id"] = an.gtfs_route_id(r.route_id)
    t = t.merge(rule[0], on=["route_id", "direction_id", "hour"], how="left")
    t = t.merge(rule[1], on=["route_id", "direction_id"], how="left").merge(rule[2], on="route_id", how="left")
    return t.standard.fillna(t.rd_standard).fillna(t.route_standard).fillna("Schedule").set_axis(t.trip_id)


def gaps(v, flag, value):
    """Flagged-minus-unflagged share of `value`, unadjusted and within route x direction x position, with
    intervals resampling days and routes."""
    v = v[v.pos_bin.notna()]
    u = v.groupby(["stop_id", "route_id", "direction_id", "pos_bin", "start_date"], observed=True)[value].agg(["sum", "size"]).reset_index()
    day, route = pd.factorize(u.start_date)[0], pd.factorize(u.route_id)[0]
    cells = {"unadjusted": np.zeros(len(u), int),
             "within route and position": pd.factorize(pd.MultiIndex.from_frame(u[["route_id", "direction_id", "pos_bin"]]))[0]}
    g = flag.reindex(u.stop_id).to_numpy(bool)
    num, den = u["sum"].to_numpy(float), u["size"].to_numpy(float)
    rows = []
    for level, cell in cells.items():
        est, share = an.within_gap(cell, g, num, den, np.ones(len(u)))
        draws = [an.within_gap(cell, g, num, den, (np.bincount(rng.integers(0, day.max() + 1, day.max() + 1), minlength=day.max() + 1)[day]
                                                  * np.bincount(rng.integers(0, route.max() + 1, route.max() + 1), minlength=route.max() + 1)[route]).astype(float))[0]
                 for _ in range(REPS)]
        lo, hi = np.nanpercentile(draws, [2.5, 97.5])
        rows.append(dict(level=level, gap=100 * est, lo=100 * lo, hi=100 * hi, mixed_share=share,
                         flagged=100 * v.loc[flag.reindex(v.stop_id).to_numpy(bool), value].mean(),
                         unflagged=100 * v.loc[~flag.reindex(v.stop_id).to_numpy(bool), value].mean(), visits=len(v)))
    return rows


def main(path, outdir, first, last, skip):
    pathlib.Path(outdir).mkdir(parents=True, exist_ok=True)
    days = weekdays(first, last, skip)
    keep = days.strftime("%Y-%m-%d")
    v = pd.read_csv(path, usecols=["kind", "start_date", "route_id", "direction_id", "trip_id", "stop_sequence", "stop_id",
                                   "scheduled_departure", "departed_at", "sched_s_from_origin"],
                    dtype={"route_id": str, "trip_id": str, "stop_id": str, "start_date": str}, engine="pyarrow")
    v = v[v.start_date.isin(keep)].copy()
    v["direction_id"] = v.direction_id.fillna(-1).astype(int)
    v["pos_bin"] = pd.cut(v.sched_s_from_origin / 60, an.POS_BINS, right=False, labels=False)
    dep = pd.to_datetime(v.departed_at, utc=True)
    v["dep_dev_s"] = (dep - pd.to_datetime(v.scheduled_departure, utc=True)).dt.total_seconds()
    v["dep_epoch"] = (dep - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()

    sched = scheduled_visits(days)
    std = standards(sched)
    v["standard"] = v.trip_id.map(std).fillna("Schedule")
    v = v.merge(sched[["start_date", "trip_id", "stop_sequence", "dep_s", "end"]], on=["start_date", "trip_id", "stop_sequence"], how="left")
    print(f"{len(v):,} weekday visits on {len(days)} days ({(v.kind == 'pass').mean():.1%} passes); "
          f"{v.dep_s.notna().mean():.1%} matched to the day's timetable; headway-run {(v.standard == 'Headway').mean():.1%}")

    stops = an.stop_attributes(pd.read_csv(an.D + "stops_bg.csv", dtype={"stop_id": str}).set_index("stop_id"))
    n = v.groupby("stop_id").size()
    stops = stops[stops.index.isin(n[n >= an.MIN_N].index)]
    inner = v[v.stop_id.isin(stops.index) & v.end.eq(False)]

    # H4: buses leaving more than a minute early, on timetable-run trips
    h4 = inner[(inner.standard == "Schedule") & inner.dep_dev_s.notna()].assign(early=lambda x: (x.dep_dev_s < EARLY_DEP_S).astype(float))

    # H5: gaps more than 1.5 times the scheduled gap to the previous scheduled trip, on headway-run trips
    key = ["start_date", "route_id", "direction_id", "stop_id"]
    s = sched.sort_values(key + ["dep_s"])
    s["sched_gap"] = s.dep_s - s.groupby(key).dep_s.shift()
    o = v[v.dep_epoch.notna()].sort_values(key + ["dep_epoch"])
    o["gap"] = o.dep_epoch - o.groupby(key).dep_epoch.shift()
    o = o.merge(s[["start_date", "trip_id", "stop_sequence", "sched_gap"]], on=["start_date", "trip_id", "stop_sequence"], how="left")
    h5 = o[o.stop_id.isin(stops.index) & o.end.eq(False) & (o.standard == "Headway") & o.gap.notna() & (o.sched_gap > 0)]
    h5 = h5.assign(long=lambda x: (x.gap > LONG_GAP * x.sched_gap).astype(float))

    rows = []
    for name, data, value in [("H4", h4, "early"), ("H5", h5, "long")]:
        for crit in an.CRITERIA:
            for r in gaps(data, stops[crit], value):
                rows.append(dict(test=name if r["level"] == "unadjusted" else name + "b", criterion=crit, **r))
    res = pd.DataFrame(rows)
    res.to_csv(f"{outdir}/table_h4_h5.csv", index=False)
    for t in ["H4", "H5"]:
        r = res[(res.test == t) & (res.criterion == "ej_income")].iloc[0]
        verdict = "supported" if r.lo > 0 else "not supported"
        print(f"{t} (primary, income criterion): {r.flagged:.1f}% vs {r.unflagged:.1f}%, gap {r.gap:+.1f} points ({r.lo:+.1f}, {r.hi:+.1f}): {verdict}")
    print(res.round(2).to_string(index=False))

    # coverage: scheduled stop visits after the first stop, by flag
    sv = sched[sched.groupby(["start_date", "trip_id"]).stop_sequence.transform("min") != sched.stop_sequence]
    sv = sv.merge(v[["start_date", "trip_id", "stop_sequence", "kind"]].drop_duplicates(["start_date", "trip_id", "stop_sequence"]),
                  on=["start_date", "trip_id", "stop_sequence"], how="left")
    logged = v[["start_date", "trip_id"]].drop_duplicates().assign(ran=True)
    sv = sv.merge(logged, on=["start_date", "trip_id"], how="left")
    sv = sv.assign(ran=sv.ran.fillna(False).astype(bool), status=sv.kind.fillna("neither"))
    allstops = an.stop_attributes(pd.read_csv(an.D + "stops_bg.csv", dtype={"stop_id": str}).set_index("stop_id"))
    sv = sv[sv.stop_id.isin(allstops.index)]
    cov = []
    for crit in an.CRITERIA:
        f = sv.stop_id.map(allstops[crit]).astype(bool)
        for flagged in (True, False):
            x = sv[f == flagged]
            r = x[x.ran]
            cov.append(dict(criterion=crit, flagged=flagged, scheduled_visits=len(x),
                            arrival=100 * (r.status == "arrival").mean(), passed=100 * (r.status == "pass").mean(),
                            neither=100 * (r.status == "neither").mean(), on_unlogged_trips=100 * (~x.ran).mean()))
    cov = pd.DataFrame(cov)
    cov.to_csv(f"{outdir}/table_coverage.csv", index=False)
    print("\ncoverage of scheduled stop visits (percent; arrival/pass/neither on trips that ran):")
    print(cov.round(1).to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:])
