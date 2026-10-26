"""Follow-up checks on analyze.py's comparisons.

Usage: python checks.py data/arrivals_window1.csv.gz output/window1_v2 [first_timetable_date last_date]

1. All three adjustment levels on the same stops: those in route x direction x position cells that hold
   both flagged and unflagged stops.
2. Unadjusted gaps weighted by stop (one vote per stop) as well as by arrival.
3. The eight primary comparisons with bootstrap p-values and a Holm correction.
4. How far apart flagged and unflagged stops sit inside the mixed cells.
5. Unobserved trips: scheduled weekday bus trips with no logged arrival (exploratory), on the dates the
   GTFS zip's calendar covers.
"""
import sys
import json
import zipfile
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
import analyze as an

REPS = 1000
PRIMARY = [("route", "ej_income", "late"), ("route", "ej_income", "error"), ("route", "ej_minority", "late"),
           ("route", "ej_minority", "error"), ("route_position", "ej_income", "late"), ("route_position", "ej_minority", "late"),
           ("route_position", "ej_income", "error"), ("route_position", "ej_minority", "error")]


def setup(path):
    a = an.load(path)
    sb = pd.read_csv(an.D + "stops_bg.csv", dtype={"stop_id": str, "GEOID": str, "ej_geoid": str}).set_index("stop_id")
    w = a[a.day_type == "weekday"].copy()
    n = w.groupby("stop_id").size()
    stops = an.stop_attributes(sb).join(n.rename("n"), how="inner")
    kept = stops[stops.n >= an.MIN_N].copy()
    return a, w, kept


def route_flags_for(w, U):
    shapes = pd.read_csv(an.D + "shapes_ej.csv", dtype={"shape_id": str}).set_index("shape_id")
    trips = w.drop_duplicates(["start_date", "trip_id"]).merge(
        pd.read_csv(an.D + "trips_bus.csv", dtype={"trip_id": str, "shape_id": str})[["trip_id", "shape_id"]], on="trip_id", how="left")
    trips = trips.groupby(["route_id", "shape_id"]).size().reset_index(name="trips").join(shapes, on="shape_id").dropna(subset=["len_m"])
    trips["wt"] = trips.trips * trips.len_m
    cols = {"ej_income": "ej_income_share", "ej_minority": "ej_minority_share", "fta_minority": "fta_minority_share"}
    rshare = pd.DataFrame({c: trips.groupby("route_id").apply(lambda t, col=col: np.average(t[col], weights=t.wt)) for c, col in cols.items()})
    route_ids = pd.factorize(U.u.route_id)[1]
    return {c: (rshare[c].reindex(route_ids).fillna(0) >= an.ROUTE_SHARE).to_numpy() for c in cols}, rshare


def stop_weighted_gap(U, flag, num, den, w):
    """One vote per stop: mean of stop means, flagged minus unflagged."""
    sidx, sids = pd.factorize(U.u.stop_id)
    A = np.bincount(sidx, weights=w * den, minlength=len(sids))
    S = np.bincount(sidx, weights=w * num, minlength=len(sids))
    f = np.zeros(len(sids), bool); f[sidx] = flag
    sw = np.bincount(sidx, weights=w, minlength=len(sids)) / np.maximum(np.bincount(sidx, minlength=len(sids)), 1)
    ok = A > 0
    m = np.where(ok, S / np.maximum(A, 1e-12), np.nan)
    return float(np.average(m[ok & f], weights=sw[ok & f]) - np.average(m[ok & ~f], weights=sw[ok & ~f]))


def mixed_subset(U, crit):
    """Units in route x direction x position cells that hold both flagged and unflagged stops."""
    cell = U.cells["route_position"]
    g = U.flags[crit]
    has = np.zeros((cell.max() + 1, 2), bool)
    has[cell, g.astype(int)] = True
    return has[cell].all(axis=1)


class Sub:
    """A Units-like view restricted to a boolean mask, sharing day and route resampling indices."""
    def __init__(self, U, mask):
        self.u = U.u[mask].reset_index(drop=True)
        self.day, self.route = U.day[mask], U.route[mask]
        self.n_days, self.n_routes = U.n_days, U.n_routes
        self.cells = {lv: pd.factorize(c[mask])[0] for lv, c in U.cells.items()}
        self.flags = {k: v[mask] for k, v in U.flags.items()}
        self.val = {m: (num[mask], den[mask]) for m, (num, den) in U.val.items()}
        self._full = U

    def weights(self, boot, dm=None, rm=None):
        if not boot:
            return np.ones(len(self.u))
        return dm[self.day] * rm[self.route]


def draw_multipliers(U):
    dm = np.bincount(an.rng.integers(0, U.n_days, U.n_days), minlength=U.n_days)
    rm = np.bincount(an.rng.integers(0, U.n_routes, U.n_routes), minlength=U.n_routes)
    return dm, rm


def summarize(point, draws):
    b = np.array(draws, float)
    b = b[~np.isnan(b)]
    p = 2 * min((b <= 0).mean(), (b >= 0).mean())
    return dict(estimate=point, ci_lo=np.percentile(b, 2.5), ci_hi=np.percentile(b, 97.5), p_boot=min(p, 1.0))


def holm(ps):
    order = np.argsort(ps)
    adj = np.empty(len(ps))
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (len(ps) - rank) * ps[i])
        adj[i] = min(running, 1.0)
    return adj


def unobserved_trips(w, z_path, route_flags_df, first, last):
    with zipfile.ZipFile(z_path) as z:
        cal = pd.read_csv(z.open("calendar.txt"), dtype=str)
        cdates = pd.read_csv(z.open("calendar_dates.txt"), dtype=str)
        trips = pd.read_csv(z.open("trips.txt"), usecols=["trip_id", "route_id", "service_id"], dtype=str)
        routes = pd.read_csv(z.open("routes.txt"), usecols=["route_id", "route_type"], dtype={"route_id": str})
    trips = trips[trips.route_id.isin(routes[routes.route_type == 3].route_id)]
    days = pd.date_range(first, last, freq="D")
    days = [d for d in days if d.dayofweek < 5]
    dow = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    rows = []
    for d in days:
        ds = d.strftime("%Y%m%d")
        active = set(cal[(cal.start_date <= ds) & (cal.end_date >= ds) & (cal[dow[d.dayofweek]] == "1")].service_id)
        active |= set(cdates[(cdates.date == ds) & (cdates.exception_type == "1")].service_id)
        active -= set(cdates[(cdates.date == ds) & (cdates.exception_type == "2")].service_id)
        t = trips[trips.service_id.isin(active)][["trip_id", "route_id"]].copy()
        t["start_date"] = d.strftime("%Y-%m-%d")
        rows.append(t)
    sched = pd.concat(rows)
    seen = w[["start_date", "trip_id"]].drop_duplicates().assign(seen=True)
    sched = sched.merge(seen, on=["start_date", "trip_id"], how="left")
    sched["seen"] = sched.seen.fillna(False).astype(bool)
    by_route = sched.groupby("route_id").agg(scheduled=("seen", "size"), observed=("seen", "sum"))
    by_route["unobserved_pct"] = 100 * (1 - by_route.observed / by_route.scheduled)
    by_route = by_route.join((route_flags_df >= an.ROUTE_SHARE).rename(columns=lambda c: c + "_route"))
    out = {"days": len(days), "scheduled": int(len(sched)), "unobserved_pct": float(100 * (1 - sched.seen.mean()))}
    for c in ["ej_income", "ej_minority", "fta_minority"]:
        f = by_route[c + "_route"].fillna(False).astype(bool)
        out[c] = {"flagged_routes_pct": float(np.average(by_route.unobserved_pct[f], weights=by_route.scheduled[f])),
                  "other_routes_pct": float(np.average(by_route.unobserved_pct[~f], weights=by_route.scheduled[~f]))}
    return out, by_route


def main(path, outdir, first=None, last=None):
    a, w, kept = setup(path)
    U = an.Units(w, kept)
    rflags, rshare = route_flags_for(w, U)
    res = {}

    # 1 and 2: common sample, both weightings
    common = []
    for crit in ["ej_income", "ej_minority", "fta_minority"]:
        mask = mixed_subset(U, crit)
        S = Sub(U, mask)
        for m, (num, den) in S.val.items():
            pts = {lv: an.within_gap(S.cells[lv], S.flags[crit], num, den, np.ones(len(S.u)))[0] for lv in an.LEVELS}
            pts["stop_weighted_unadjusted"] = stop_weighted_gap(S, S.flags[crit], num, den, np.ones(len(S.u)))
            pts["stop_weighted_unadjusted_all_stops"] = stop_weighted_gap(U, U.flags[crit], *U.val[m], np.ones(len(U.u)))
            draws = {k: [] for k in pts}
            for _ in range(REPS // 2):
                dm, rm = draw_multipliers(U)
                ws, wu = S.weights(True, dm, rm), dm[U.day] * rm[U.route]
                for lv in an.LEVELS:
                    draws[lv].append(an.within_gap(S.cells[lv], S.flags[crit], num, den, ws)[0])
                draws["stop_weighted_unadjusted"].append(stop_weighted_gap(S, S.flags[crit], num, den, ws))
                draws["stop_weighted_unadjusted_all_stops"].append(stop_weighted_gap(U, U.flags[crit], *U.val[m], wu))
            for k, v in pts.items():
                common.append(dict(criterion=crit, measure=m, column=k, stops=int(S.u.stop_id.nunique()) if "all_stops" not in k else int(U.u.stop_id.nunique()),
                                   arrival_share=float(S.val[m][1].sum() / U.val[m][1].sum()) if "all_stops" not in k else 1.0,
                                   **summarize(v, draws[k])))
    pd.DataFrame(common).to_csv(f"{outdir}/table_common_sample.csv", index=False)

    # 3: primary comparisons, joint draws
    def primaries(boot, dm=None, rm=None):
        ww = np.ones(len(U.u)) if not boot else dm[U.day] * rm[U.route]
        out = []
        for lv, crit, m in PRIMARY:
            num, den = U.val[m]
            out.append(an.route_gap(U, rflags[crit], num, den, ww) if lv == "route" else an.within_gap(U.cells[lv], U.flags[crit], num, den, ww)[0])
        return out
    pt = primaries(False)
    dr = np.array([primaries(True, *draw_multipliers(U)) for _ in range(REPS)])
    prim = []
    for i, (lv, crit, m) in enumerate(PRIMARY):
        prim.append(dict(hypothesis={"route": "H1"}.get(lv, "H2" if m == "late" else "H3"), level=lv, criterion=crit, measure=m, **summarize(pt[i], dr[:, i])))
    prim = pd.DataFrame(prim)
    prim["p_holm"] = holm(prim.p_boot.to_numpy())
    prim.to_csv(f"{outdir}/table_primary.csv", index=False)

    # 4: distance from flagged stops to the nearest unflagged stop in the same mixed cell
    xy = kept[["x", "y"]]
    sc = U.u[["stop_id", "route_id", "direction_id", "pos_bin"]].drop_duplicates()
    sc["cell"] = pd.factorize(pd.MultiIndex.from_frame(sc[["route_id", "direction_id", "pos_bin"]]))[0]
    sc = sc.join(xy, on="stop_id")
    for crit in ["ej_income", "ej_minority", "fta_minority"]:
        sc["f"] = kept[crit].reindex(sc.stop_id).to_numpy()
        dists, spacing = [], []
        for _, c in sc.groupby("cell"):
            fl, un = c[c.f], c[~c.f]
            if len(c) > 1:
                t_all = cKDTree(c[["x", "y"]].to_numpy())
                spacing.extend(t_all.query(c[["x", "y"]].to_numpy(), k=2)[0][:, 1])
            if len(fl) and len(un):
                dists.extend(cKDTree(un[["x", "y"]].to_numpy()).query(fl[["x", "y"]].to_numpy())[0])
        res[f"mixed_cell_distance_{crit}"] = dict(median_m=float(np.median(dists)), p75_m=float(np.percentile(dists, 75)),
                                                  median_stop_spacing_m=float(np.median(spacing)))

    # 5: unobserved trips
    if first and last:
        res["unobserved_trips"], by_route = unobserved_trips(w, an.D + "MBTA_GTFS.zip", rshare, first, last)
        by_route.to_csv(f"{outdir}/table_unobserved_trips.csv")

    with open(f"{outdir}/checks.json", "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    print(prim.round(4).to_string())
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main(*sys.argv[1:])
