"""Stop- and route-level comparison of bus lateness, early arrivals and MBTA prediction error by neighborhood.

Usage: python analyze.py data/arrivals_window1.csv.gz output/window1_v2

Within-route comparisons are within-cell contrasts (route x direction x position bin), so a stop is only
compared with stops of the other group in its own cell; cells holding one group contribute nothing.
Intervals come from a two-way bootstrap that resamples service days and routes together.
"""
import os
import sys
import json
import numpy as np
import pandas as pd
import geopandas as gpd
from libpysal.weights import DistanceBand
from esda.getisord import G_Local
from esda import fdr

D = "data/"
LATE_S, EARLY_S = 300, -60
MIN_N = 100
SENSITIVITY_N = [50, 200]
POS_BINS = [0, 2, 5, 10, 15, 20, 30, 45, 60, 1e9]
ROUTE_SHARE = 1 / 3
BAND_M = 500
REPS = 1000
rng = np.random.default_rng(20261025)

MEASURES = {"late": ("late", "n"), "early": ("early", "n"), "error": ("err", "n_err")}
CRITERIA = {"ej_income": "EJ income", "ej_minority": "EJ minority", "fta_minority": "Above service-area minority share"}
CONTINUOUS = {"income_25k": "Median household income, per $25,000", "minority_10": "Minority share, per 10 points",
              "black_10": "Black share, per 10 points", "hispanic_10": "Hispanic share, per 10 points"}
LEVELS = {"none": [], "route": ["route_id", "direction_id"], "route_position": ["route_id", "direction_id", "pos_bin"]}


def load(path):
    a = pd.read_csv(path, usecols=["start_date", "route_id", "direction_id", "trip_id", "stop_sequence", "stop_id",
                                   "late_s", "feed_300", "sched_s_from_origin"],
                    dtype={"route_id": str, "trip_id": str, "stop_id": str, "start_date": str, "direction_id": "float64",
                           "stop_sequence": "float64", "late_s": "float64", "feed_300": "float64",
                           "sched_s_from_origin": "float64"}, engine="pyarrow")
    d = pd.to_datetime(a.start_date)
    a["day_type"] = np.where((d.dt.dayofweek < 5) & (a.start_date != "2026-10-12"), "weekday",
                             np.where(d.dt.dayofweek == 5, "saturday", "sunday/holiday"))
    a["late"] = (a.late_s > LATE_S).astype(float)
    a["early"] = (a.late_s < EARLY_S).astype(float)
    a["err"] = a.feed_300.abs()
    a["pos_bin"] = pd.cut(a.sched_s_from_origin / 60, POS_BINS, right=False, labels=False)
    tp = pd.read_csv(D + "timepoints.csv", dtype={"trip_id": str, "stop_sequence": "float64", "timepoint": "float64"})
    a = a.merge(tp, on=["trip_id", "stop_sequence"], how="left")
    return a


def stop_attributes(sb):
    s = sb.copy()
    for c in CRITERIA:
        s[c] = s[c].fillna(False).astype(bool)
    s["income_25k"] = s.mhhi / 25000
    s["minority_10"] = s.minority_share * 10
    s["black_10"] = s.black_share * 10
    s["hispanic_10"] = s.hispanic_share * 10
    return s


class Units:
    """Arrivals summed to (stop, route, direction, position bin, day) units, with index arrays for fast resampling."""

    def __init__(self, w, stops):
        w = w[w.pos_bin.notna()].copy()
        w["n_err"] = w.err.notna().astype(float)
        w["err"] = w.err.fillna(0.0)
        keys = ["stop_id", "route_id", "direction_id", "pos_bin", "start_date"]
        u = w.groupby(keys, observed=True).agg(n=("late", "size"), late=("late", "sum"), early=("early", "sum"),
                                                err=("err", "sum"), n_err=("n_err", "sum")).reset_index()
        u = u[u.stop_id.isin(stops.index)].reset_index(drop=True)
        self.u = u
        self.day = pd.factorize(u.start_date)[0]
        self.route = pd.factorize(u.route_id)[0]
        self.n_days, self.n_routes = self.day.max() + 1, self.route.max() + 1
        self.cells = {lv: (pd.factorize(pd.MultiIndex.from_frame(u[cols]))[0] if cols else np.zeros(len(u), int))
                      for lv, cols in LEVELS.items()}
        self.stop_cell = pd.factorize(pd.MultiIndex.from_frame(u[["stop_id", "route_id", "direction_id", "pos_bin"]]))[0]
        st = stops.reindex(u.stop_id)
        self.flags = {c: st[c].to_numpy(bool) for c in CRITERIA}
        self.x = {c: st[c].to_numpy(float) for c in CONTINUOUS}
        self.val = {m: (u[num].to_numpy(float), u[den].to_numpy(float)) for m, (num, den) in MEASURES.items()}

    def weights(self, boot):
        if not boot:
            return np.ones(len(self.u))
        dm = np.bincount(rng.integers(0, self.n_days, self.n_days), minlength=self.n_days)
        rm = np.bincount(rng.integers(0, self.n_routes, self.n_routes), minlength=self.n_routes)
        return dm[self.day] * rm[self.route]


def within_gap(cell, g, num, den, w):
    """Arrival-weighted flagged-minus-unflagged gap inside each cell, averaged over cells holding both groups
    with fixed-effects weights A1*A0/(A1+A0)."""
    nc = cell.max() + 1
    idx = cell * 2 + g.astype(int)
    A = np.bincount(idx, weights=w * den, minlength=2 * nc).reshape(nc, 2)
    S = np.bincount(idx, weights=w * num, minlength=2 * nc).reshape(nc, 2)
    ok = (A[:, 0] > 0) & (A[:, 1] > 0)
    if not ok.any():
        return np.nan, 0.0
    gap = S[ok, 1] / A[ok, 1] - S[ok, 0] / A[ok, 0]
    wt = A[ok, 0] * A[ok, 1] / (A[ok, 0] + A[ok, 1])
    return float((wt * gap).sum() / wt.sum()), float(A[ok].sum() / A.sum())


def within_slope(cell, stop_cell, x, num, den, w):
    """Fixed-effects slope of a stop-cell's mean on x, within cells, weighted by arrivals."""
    good = ~np.isnan(x)
    n_sc = stop_cell.max() + 1
    A = np.bincount(stop_cell[good], weights=(w * den)[good], minlength=n_sc)
    S = np.bincount(stop_cell[good], weights=(w * num)[good], minlength=n_sc)
    xs = np.zeros(n_sc); xs[stop_cell[good]] = x[good]
    cs = np.zeros(n_sc, int); cs[stop_cell] = cell
    keep = A > 0
    A, S, xs, cs = A[keep], S[keep], xs[keep], cs[keep]
    y = S / A
    nc = cs.max() + 1
    Wc = np.bincount(cs, weights=A, minlength=nc)
    xm = np.bincount(cs, weights=A * xs, minlength=nc) / np.maximum(Wc, 1e-12)
    ym = np.bincount(cs, weights=A * y, minlength=nc) / np.maximum(Wc, 1e-12)
    dx, dy = xs - xm[cs], y - ym[cs]
    sxx = (A * dx * dx).sum()
    return float((A * dx * dy).sum() / sxx) if sxx > 0 else np.nan


def route_gap(U, route_flag, num, den, w):
    A = np.bincount(U.route, weights=w * den, minlength=U.n_routes)
    S = np.bincount(U.route, weights=w * num, minlength=U.n_routes)
    mult = np.bincount(U.route, weights=w, minlength=U.n_routes) > 0
    ok = mult & (A > 0)
    m = np.where(ok, S / np.maximum(A, 1e-12), np.nan)
    # routes count once per draw: weight each by its multiplicity in the resample
    rw = np.bincount(U.route, weights=w, minlength=U.n_routes)
    rw = rw / np.maximum(np.bincount(U.route, minlength=U.n_routes), 1)
    f = route_flag
    a1, a0 = ok & f, ok & ~f
    if not a1.any() or not a0.any():
        return np.nan
    return float(np.average(m[a1], weights=rw[a1]) - np.average(m[a0], weights=rw[a0]))


def run(U, route_flags, reps=REPS, levels=LEVELS, criteria=CRITERIA, continuous=CONTINUOUS, do_routes=True):
    """Point estimates and two-way bootstrap intervals for every comparison."""
    def one(boot):
        w = U.weights(boot)
        out = {}
        for m, (num, den) in U.val.items():
            for c in criteria:
                for lv in levels:
                    gap, share = within_gap(U.cells[lv], U.flags[c], num, den, w)
                    out[("gap", c, m, lv)] = gap
                    if not boot:
                        out[("mixed_share", c, m, lv)] = share
                if do_routes:
                    out[("route", c, m, "route")] = route_gap(U, route_flags[c], num, den, w)
            for x in continuous:
                for lv in ["none", "route_position"]:
                    out[("slope", x, m, lv)] = within_slope(U.cells[lv], U.stop_cell, U.x[x], num, den, w)
        return out
    point = one(False)
    draws = [one(True) for _ in range(reps)]
    rows = []
    for k, v in point.items():
        if k[0] == "mixed_share":
            continue
        b = np.array([d[k] for d in draws], float)
        b = b[~np.isnan(b)]
        rows.append(dict(kind=k[0], var=k[1], measure=k[2], level=k[3], estimate=v,
                         ci_lo=np.percentile(b, 2.5) if len(b) else np.nan,
                         ci_hi=np.percentile(b, 97.5) if len(b) else np.nan,
                         mixed_share=point.get(("mixed_share", k[1], k[2], k[3]), np.nan)))
    return pd.DataFrame(rows)


def loo_adjusted(U, num, den):
    """Each stop relative to the other stops in its cells (leave-one-out), averaged over its cells by arrivals."""
    cell = U.cells["route_position"]
    sc = U.stop_cell
    n_sc, nc = sc.max() + 1, cell.max() + 1
    A_sc = np.bincount(sc, weights=den, minlength=n_sc)
    S_sc = np.bincount(sc, weights=num, minlength=n_sc)
    c_of = np.zeros(n_sc, int); c_of[sc] = cell
    A_c = np.bincount(c_of, weights=A_sc, minlength=nc)
    S_c = np.bincount(c_of, weights=S_sc, minlength=nc)
    other_A = A_c[c_of] - A_sc
    ok = (A_sc > 0) & (other_A > 0)
    resid = np.where(ok, S_sc / np.maximum(A_sc, 1e-12) - (S_c[c_of] - S_sc) / np.maximum(other_A, 1e-12), np.nan)
    stop_of = pd.factorize(U.u.stop_id)[1]
    sidx = np.zeros(n_sc, int); sidx[sc] = pd.factorize(U.u.stop_id)[0]
    wts = np.where(ok, A_sc, 0.0)
    tot = np.bincount(sidx, weights=wts, minlength=len(stop_of))
    val = np.bincount(sidx, weights=np.nan_to_num(resid) * wts, minlength=len(stop_of))
    return pd.Series(np.where(tot > 0, val / np.maximum(tot, 1e-12), np.nan), index=stop_of)


def hot_spots(st, cols, band=BAND_M, permutations=999):
    g = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.x, st.y), crs=26986)
    wt = DistanceBand.from_dataframe(g, threshold=band, binary=True, silence_warnings=True)
    out = g[["stop_name", "main_route", "n", "x", "y", "lon", "lat", "ej_income", "ej_minority", "fta_minority"]].copy()
    for c in cols:
        y = g[c].fillna(g[c].mean()).to_numpy()
        lg = G_Local(y, wt, transform="B", star=True, permutations=permutations, seed=20261025)
        sig = fdr(lg.p_sim, 0.05)
        out[c + "_z"] = lg.Zs
        out[c + "_class"] = np.where(lg.p_sim <= sig, np.where(lg.Zs > 0, "hot", "cold"), "")
    return out


def main(path, outdir):
    os.makedirs(outdir, exist_ok=True)
    a = load(path)
    sb = pd.read_csv(D + "stops_bg.csv", dtype={"stop_id": str, "GEOID": str, "ej_geoid": str}).set_index("stop_id")
    res = {}

    summary = a.groupby("day_type").agg(days=("start_date", "nunique"), arrivals=("late", "size"),
                                        stops=("stop_id", "nunique"), routes=("route_id", "nunique"),
                                        late_pct=("late", lambda x: 100 * x.mean()), early_pct=("early", lambda x: 100 * x.mean()),
                                        mbta_mae_s=("err", "mean"), pred_coverage_pct=("err", lambda x: 100 * x.notna().mean()))
    summary.round(1).to_csv(f"{outdir}/table_data_summary.csv")

    w = a[a.day_type == "weekday"].copy()
    f = w.feed_300.dropna()
    res["overall"] = dict(arrivals=int(len(w)), late_pct=100 * w.late.mean(), early_pct=100 * w.early.mean(),
                          median_late_s=float(w.late_s.median()), mae_s=float(f.abs().mean()), median_abs_s=float(f.abs().median()),
                          bias_s=float(f.mean()), share_later_than_predicted=100 * float((f < 0).mean()),
                          mean_shortfall_when_later_s=float(-f[f < 0].mean()),
                          mae_after_removing_bias_s=float((f - f.mean()).abs().mean()),
                          timepoint_coverage_pct=100 * float(w.timepoint.notna().mean()))
    tp = w[w.timepoint.notna()]
    res["timepoint_vs_other"] = {str(int(k)): dict(arrivals=int(len(g)), late_pct=100 * g.late.mean(), early_pct=100 * g.early.mean(),
                                                   mae_s=float(g.err.mean())) for k, g in tp.groupby("timepoint")}

    n = w.groupby("stop_id").size()
    stops = stop_attributes(sb).join(n.rename("n"), how="inner")
    top = w.groupby(["stop_id", "route_id"]).size().reset_index(name="c").sort_values("c", ascending=False)
    stops["main_route"] = top.drop_duplicates("stop_id").set_index("stop_id").route_id
    g = w.groupby("stop_id")
    stops["late_share"], stops["early_share"], stops["mae"] = g.late.mean(), g.early.mean(), g.err.mean()
    stops["pos_min_mean"] = (g.sched_s_from_origin.mean() / 60)
    kept = stops[stops.n >= MIN_N].copy()
    res["stops_total"], res["stops_kept"] = int(len(stops)), int(len(kept))
    res["kept_pct"] = {c: 100 * float(kept[c].mean()) for c in CRITERIA}

    # route flags (trip-weighted share of length in flagged block groups)
    shapes = pd.read_csv(D + "shapes_ej.csv", dtype={"shape_id": str}).set_index("shape_id")
    trips = w.drop_duplicates(["start_date", "trip_id"]).merge(
        pd.read_csv(D + "trips_bus.csv", dtype={"trip_id": str, "shape_id": str})[["trip_id", "shape_id"]], on="trip_id", how="left")
    trips = trips.groupby(["route_id", "shape_id"]).size().reset_index(name="trips").join(shapes, on="shape_id").dropna(subset=["len_m"])
    trips["wt"] = trips.trips * trips.len_m
    share_cols = {"ej_income": "ej_income_share", "ej_minority": "ej_minority_share", "fta_minority": "fta_minority_share"}
    rshare = pd.DataFrame({c: trips.groupby("route_id").apply(lambda t, col=col: np.average(t[col], weights=t.wt))
                           for c, col in share_cols.items()})
    rshare.to_csv(f"{outdir}/table_route_shares.csv")
    res["routes_flagged"] = {c: int((rshare[c] >= ROUTE_SHARE).sum()) for c in CRITERIA}
    res["routes_total"] = int(len(rshare))

    U = Units(w, kept)
    route_ids = pd.factorize(U.u.route_id)[1]
    route_flags = {c: (rshare[c].reindex(route_ids).fillna(0) >= ROUTE_SHARE).to_numpy() for c in CRITERIA}
    res["cells"] = {lv: int(U.cells[lv].max() + 1) for lv in LEVELS}

    est = run(U, route_flags)
    est.to_csv(f"{outdir}/table_estimates.csv", index=False)

    # sensitivity to the arrival minimum, within route and position
    sens = []
    for m_n in SENSITIVITY_N:
        Us = Units(w, stops[stops.n >= m_n])
        e = run(Us, route_flags, reps=300, levels={"route_position": LEVELS["route_position"]}, continuous={}, do_routes=False)
        e["min_n"] = m_n
        sens.append(e)
    # timepoint arrivals only
    Ut = Units(w[w.timepoint == 1], kept)
    e = run(Ut, route_flags, reps=300, levels={"route_position": LEVELS["route_position"]}, continuous={}, do_routes=False)
    e["min_n"] = "timepoints only"
    sens.append(e)
    pd.concat(sens).to_csv(f"{outdir}/table_sensitivity.csv", index=False)

    # position table
    pos = w.groupby("pos_bin").agg(arrivals=("late", "size"), late_pct=("late", lambda x: 100 * x.mean()),
                                   early_pct=("early", lambda x: 100 * x.mean()), mbta_mae_s=("err", "mean"),
                                   mbta_bias_s=("feed_300", "mean"), mean_late_s=("late_s", "mean"))
    pos.index = [f"{POS_BINS[i]:g}-{POS_BINS[i + 1]:g} min" if POS_BINS[i + 1] < 1e9 else f"{POS_BINS[i]:g}+ min"
                 for i in pos.index.astype(int)]
    pos.round(1).to_csv(f"{outdir}/table_position.csv")

    # income quintiles and their overlap with the EJ income flag
    kept["mhhi_quintile"] = pd.qcut(kept.mhhi, 5, labels=False) + 1
    for m, (num, den) in MEASURES.items():
        kept[m + "_adj"] = loo_adjusted(U, *U.val[m]).reindex(kept.index)
    q = kept.groupby("mhhi_quintile").agg(stops=("n", "size"), mhhi_lo=("mhhi", "min"), mhhi_hi=("mhhi", "max"),
                                          ej_income_flagged=("ej_income", "sum"), late_share=("late_share", "mean"),
                                          late_adj=("late_adj", "mean"), early_share=("early_share", "mean"),
                                          mae=("mae", "mean"), error_adj=("error_adj", "mean"))
    q.to_csv(f"{outdir}/table_income_quintiles.csv")
    kept.to_csv(f"{outdir}/table_stop_measures.csv")

    # hot spots on raw and leave-one-out adjusted measures
    hs = hot_spots(kept.reset_index(), ["late_share", "mae", "late_adj", "error_adj"])
    hs = hs.rename(columns={"late_adj_z": "late_r_z", "late_adj_class": "late_r_class", "error_adj_z": "err_r_z", "error_adj_class": "err_r_class"})
    hs.to_csv(f"{outdir}/hotspots.csv", index=False)
    for c in ["late_share", "mae", "late_r", "err_r"]:
        for k in ["hot", "cold"]:
            sel = hs[hs[c + "_class"] == k]
            res[f"{c}_{k}_stops"] = int(len(sel))
            for crit in CRITERIA:
                res[f"{c}_{k}_pct_{crit}"] = float(100 * sel[crit].mean()) if len(sel) else None
            res[f"{c}_{k}_top_routes"] = sel.main_route.value_counts().head(5).to_dict()
    with open(f"{outdir}/results.json", "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
