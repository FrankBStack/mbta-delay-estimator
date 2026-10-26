"""Stop- and route-level analysis of bus lateness and prediction error by neighborhood.

Usage: python analyze.py data/arrivals_window1.csv.gz output/window1

Reads the exported arrivals plus stops_bg.csv and shapes_ej.csv from prep_neighborhoods.py.
Writes tables (CSV), hot spot results and a results.md summary into the output directory.
"""
import sys
import json
import numpy as np
import pandas as pd
import geopandas as gpd
from libpysal.weights import DistanceBand
from esda.getisord import G_Local
from esda import fdr

D = "data/"
LATE_S = 300            # more than five minutes late
MIN_N = 100             # arrivals per stop for the main analysis
SENSITIVITY_N = [50, 200]
POS_BINS = [0, 2, 5, 10, 15, 20, 30, 45, 60, 1e9]   # scheduled minutes from the trip origin
ROUTE_SHARE = 1 / 3     # share of route length in flagged areas, after Title VI's one-third rule
BAND_M = 500            # hot spot distance band
BOOT = 2000
rng = np.random.default_rng(20261025)


def load(path):
    a = pd.read_csv(path, dtype={"route_id": str, "trip_id": str, "shape_id": str, "stop_id": str,
                                 "start_date": str, "direction_id": "float64", "stop_sequence": "float64",
                                 "late_s": "float64", "feed_300": "float64", "position_300": "float64",
                                 "frac": "float64", "sched_s_from_origin": "float64"},
                    usecols=["start_date", "route_id", "direction_id", "trip_id", "shape_id", "stop_sequence",
                             "stop_id", "late_s", "feed_300", "position_300", "frac", "sched_s_from_origin"],
                    engine="pyarrow")
    d = pd.to_datetime(a.start_date)
    a["day_type"] = np.where((d.dt.dayofweek < 5) & (a.start_date != "2026-10-12"), "weekday",
                             np.where(d.dt.dayofweek == 5, "saturday", "sunday/holiday"))
    a["late"] = (a.late_s > LATE_S).astype(float)
    a["abs_err"] = a.feed_300.abs()
    a["pos_min"] = a.sched_s_from_origin / 60
    a["pos_bin"] = pd.cut(a.pos_min, POS_BINS, right=False, labels=False)
    return a


def per_stop(w):
    g = w.groupby("stop_id")
    s = pd.DataFrame({"n": g.size(), "late_share": g.late.mean(), "n_pred": g.feed_300.count(),
                      "mae": g.abs_err.mean(), "bias": g.feed_300.mean(),
                      "pos_min_mean": g.pos_min.mean()})
    # the route with the most arrivals at the stop
    top = w.groupby(["stop_id", "route_id"]).size().reset_index(name="c").sort_values("c", ascending=False)
    s["main_route"] = top.drop_duplicates("stop_id").set_index("stop_id").route_id
    return s


def residualize(w):
    """Subtract each arrival's route x direction x position-bin mean, so a stop's residual compares it
    with the same route at the same point along it."""
    w = w[w.pos_bin.notna()].copy()
    key = ["route_id", "direction_id", "pos_bin"]
    w["late_r"] = w.late - w.groupby(key).late.transform("mean")
    ok = w.abs_err.notna()
    w.loc[ok, "err_r"] = w.abs_err[ok] - w[ok].groupby(key).abs_err.transform("mean")
    return w


def day_matrix(w, col):
    """(stop x day) sums and counts of a column, for the day-level bootstrap."""
    x = w[w[col].notna()]
    sums = x.pivot_table(index="stop_id", columns="start_date", values=col, aggfunc="sum", fill_value=0.0)
    cnts = x.pivot_table(index="stop_id", columns="start_date", values=col, aggfunc="count", fill_value=0)
    return sums, cnts


def stop_gap(sums, cnts, flag, keep, reps=BOOT):
    """Gap in per-stop means between flagged and unflagged stops, with a bootstrap over service days."""
    idx = sums.index.intersection(keep)
    S, C = sums.loc[idx].to_numpy(), cnts.loc[idx].to_numpy()
    f = flag.reindex(idx).to_numpy()
    ndays = S.shape[1]

    def gap(cols):
        m = S[:, cols].sum(1) / np.maximum(C[:, cols].sum(1), 1)
        has = C[:, cols].sum(1) > 0
        return m[f & has].mean() - m[~f & has].mean()

    point = gap(np.arange(ndays))
    boots = np.array([gap(rng.integers(0, ndays, ndays)) for _ in range(reps)])
    return point, np.percentile(boots, 2.5), np.percentile(boots, 97.5), int(f.sum()), int((~f).sum())


def within_route_keep(stops, flag_col):
    """Stops on routes that have both flagged and unflagged stops."""
    both = stops.groupby("main_route")[flag_col].agg(["any", "all"])
    routes = both.index[both["any"] & ~both["all"]]
    return stops.index[stops.main_route.isin(routes)]


def route_level(w, stops_bg):
    shapes = pd.read_csv(D + "shapes_ej.csv", dtype={"shape_id": str}).set_index("shape_id")
    trips = w.drop_duplicates(["start_date", "trip_id"]).groupby(["route_id", "shape_id"]).size().reset_index(name="trips")
    trips = trips.join(shapes, on="shape_id").dropna(subset=["len_m"])
    trips["wt"] = trips.trips * trips.len_m
    r = pd.DataFrame({c: trips.groupby("route_id").apply(lambda g: np.average(g[c + "_share"], weights=g.wt))
                      for c in ["ej_any", "ej_income", "ej_minority"]})
    g = w.groupby("route_id")
    r["arrivals"] = g.size()
    r["stops"] = g.stop_id.nunique()
    r["late_share"] = g.late.mean()
    r["mae"] = g.abs_err.mean()
    r["bias"] = g.feed_300.mean()
    return r


def route_gap(r, share_col, outcome, reps=BOOT):
    f = (r[share_col] >= ROUTE_SHARE).to_numpy()
    y = r[outcome].to_numpy()

    def gap(ix):
        ff, yy = f[ix], y[ix]
        return yy[ff].mean() - yy[~ff].mean()

    ix = np.arange(len(r))
    boots = np.array([gap(rng.integers(0, len(r), len(r))) for _ in range(reps)])
    return gap(ix), np.percentile(boots, 2.5), np.percentile(boots, 97.5), int(f.sum()), int((~f).sum())


def hot_spots(stops, cols, band=BAND_M, permutations=999):
    g = gpd.GeoDataFrame(stops, geometry=gpd.points_from_xy(stops.x, stops.y), crs=26986)
    w = DistanceBand.from_dataframe(g, threshold=band, binary=True, silence_warnings=True)
    out = g[["stop_name", "main_route", "n", "x", "y", "lon", "lat", "ej_income", "ej_minority", "ej_any"]].copy()
    for c in cols:
        y = g[c].fillna(g[c].mean()).to_numpy()
        lg = G_Local(y, w, transform="B", star=True, permutations=permutations, seed=20261025)
        sig = fdr(lg.p_sim, 0.05)
        out[c + "_z"] = lg.Zs
        out[c + "_p"] = lg.p_sim
        out[c + "_class"] = np.where(lg.p_sim <= sig, np.where(lg.Zs > 0, "hot", "cold"), "")
    out["neighbors"] = pd.Series(w.cardinalities).reindex(range(len(g))).fillna(0).astype(int).to_numpy()
    return out


def main(path, outdir):
    import os
    os.makedirs(outdir, exist_ok=True)
    a = load(path)
    sb = pd.read_csv(D + "stops_bg.csv", dtype={"stop_id": str, "GEOID": str, "ej_geoid": str}).set_index("stop_id")
    routes = pd.read_csv(D + "routes.csv", dtype={"route_id": str}).set_index("route_id")
    res = {}

    summary = a.groupby("day_type").agg(days=("start_date", "nunique"), arrivals=("late", "size"),
                                        stops=("stop_id", "nunique"), routes=("route_id", "nunique"),
                                        late_pct=("late", lambda x: 100 * x.mean()), mbta_mae_s=("abs_err", "mean"),
                                        pred_coverage_pct=("feed_300", lambda x: 100 * x.notna().mean()))
    summary.round(1).to_csv(f"{outdir}/table_data_summary.csv")

    w = a[a.day_type == "weekday"]
    w = residualize(w)
    stops = per_stop(w).join(sb, how="left")
    sr = w.groupby("stop_id")[["late_r", "err_r"]].mean()
    stops = stops.join(sr)
    stops["mhhi_quintile"] = pd.qcut(stops.mhhi, 5, labels=False) + 1
    stops.to_csv(f"{outdir}/table_stop_measures.csv")

    # Hypothesis 1: route level
    r = route_level(w, sb).join(routes[["route_short_name", "route_long_name"]])
    r.to_csv(f"{outdir}/table_route_level.csv")
    rows = []
    for crit in ["ej_income", "ej_minority"]:
        for outcome, unit in [("late_share", "share late"), ("mae", "MBTA 5-min error s")]:
            gp, lo, hi, nf, nu = route_gap(r, crit, outcome)
            rows.append(dict(level="route", criterion=crit, outcome=outcome, gap=gp, ci_lo=lo, ci_hi=hi,
                             n_flagged=nf, n_unflagged=nu,
                             spearman=r[[crit, outcome]].corr(method="spearman").iloc[0, 1]))

    # Hypotheses 2 and 3: within route, same position, stops with enough arrivals
    sums_l, cnts_l = day_matrix(w, "late_r")
    sums_e, cnts_e = day_matrix(w, "err_r")
    sums_raw, cnts_raw = day_matrix(w, "late")
    sums_rawe, cnts_rawe = day_matrix(w, "abs_err")
    for min_n in [MIN_N] + SENSITIVITY_N:
        kept = stops[stops.n >= min_n]
        for crit in ["ej_income", "ej_minority"]:
            keep = within_route_keep(kept, crit)
            flag = kept[crit].fillna(False).astype(bool)
            for outcome, (S, C) in [("late_share", (sums_l, cnts_l)), ("mae", (sums_e, cnts_e))]:
                gp, lo, hi, nf, nu = stop_gap(S, C, flag, keep)
                rows.append(dict(level="stop, within route and position", criterion=crit, outcome=outcome,
                                 gap=gp, ci_lo=lo, ci_hi=hi, n_flagged=nf, n_unflagged=nu, min_n=min_n))
            if min_n == MIN_N:
                for outcome, (S, C) in [("late_share", (sums_raw, cnts_raw)), ("mae", (sums_rawe, cnts_rawe))]:
                    gp, lo, hi, nf, nu = stop_gap(S, C, flag, kept.index)
                    rows.append(dict(level="stop, raw", criterion=crit, outcome=outcome, gap=gp, ci_lo=lo,
                                     ci_hi=hi, n_flagged=nf, n_unflagged=nu, min_n=min_n))
    gaps = pd.DataFrame(rows)
    gaps.to_csv(f"{outdir}/table_gaps.csv", index=False)

    # Income as a gradient
    kept = stops[stops.n >= MIN_N]
    q = kept.groupby("mhhi_quintile").agg(stops=("n", "size"), mhhi_lo=("mhhi", "min"), mhhi_hi=("mhhi", "max"),
                                          late_share=("late_share", "mean"), late_resid=("late_r", "mean"),
                                          mae=("mae", "mean"), mae_resid=("err_r", "mean"))
    q.to_csv(f"{outdir}/table_income_quintiles.csv")
    res["spearman_income_late_resid"] = kept[["mhhi", "late_r"]].corr(method="spearman").iloc[0, 1]
    res["spearman_income_err_resid"] = kept[["mhhi", "err_r"]].corr(method="spearman").iloc[0, 1]

    # Position along the route, the confounder
    pos = w.groupby("pos_bin").agg(arrivals=("late", "size"), late_pct=("late", lambda x: 100 * x.mean()),
                                   mbta_mae_s=("abs_err", "mean"), mbta_bias_s=("feed_300", "mean"))
    pos.index = [f"{POS_BINS[i]:g}-{POS_BINS[i + 1]:g} min" if POS_BINS[i + 1] < 1e9 else f"{POS_BINS[i]:g}+ min"
                 for i in pos.index.astype(int)]
    pos.round(1).to_csv(f"{outdir}/table_position.csv")

    # Hot spots on the raw and residual measures
    hs = hot_spots(kept.reset_index(), ["late_share", "mae", "late_r", "err_r"])
    hs.to_csv(f"{outdir}/hotspots.csv", index=False)
    for c in ["late_share", "mae", "late_r", "err_r"]:
        cls = hs[c + "_class"]
        for k in ["hot", "cold"]:
            sel = hs[cls == k]
            res[f"{c}_{k}_stops"] = int(len(sel))
            res[f"{c}_{k}_pct_ej_income"] = float(100 * sel.ej_income.mean()) if len(sel) else None
            res[f"{c}_{k}_pct_ej_minority"] = float(100 * sel.ej_minority.mean()) if len(sel) else None
            res[f"{c}_{k}_top_routes"] = sel.main_route.value_counts().head(5).to_dict()
    res["kept_pct_ej_income"] = float(100 * kept.ej_income.mean())
    res["kept_pct_ej_minority"] = float(100 * kept.ej_minority.mean())
    res["stops_total"] = int(len(stops))
    res["stops_kept"] = int(len(kept))
    with open(f"{outdir}/results.json", "w") as f:
        json.dump(res, f, indent=1, default=str)
    print(summary.round(1).to_string())
    print(gaps.round(3).to_string())
    print(pos.round(1).to_string())
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
