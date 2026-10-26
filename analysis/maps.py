"""Maps for the paper, from analyze.py's output.

Usage: python maps.py output/window1
"""
import sys
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely import wkt

D = "data/"
SEQ = ["#b7d3f6", "#6da7ec", "#2a78d6", "#184f95", "#0d366b"]   # blue ramp, steps 150-700
HOT, COLD, NS = "#e34948", "#2a78d6", "#c3c2b7"
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"
EJ_INCOME, EJ_MINORITY = "#f9d2c2", "#dcebfa"
plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "axes.edgecolor": GRID, "text.color": INK})


def network():
    shp = pd.read_csv(D + "shapes_bus.csv", dtype={"shape_id": str})
    return gpd.GeoDataFrame(shp, geometry=shp.wkt.map(wkt.loads), crs=4326).to_crs(26986)


def base(ax, net, bounds, pad=1500):
    net.plot(ax=ax, color=GRID, linewidth=0.5, zorder=1)
    ax.set_xlim(bounds[0] - pad, bounds[2] + pad)
    ax.set_ylim(bounds[1] - pad, bounds[3] + pad)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    for s in ax.spines.values():
        s.set_visible(False)
    # 5 km scale bar, bottom left
    x0, y0 = bounds[0] - pad + 1500, bounds[1] - pad + 1500
    ax.plot([x0, x0 + 5000], [y0, y0], color=INK, linewidth=1.5)
    ax.text(x0 + 2500, y0 + 300, "5 km", ha="center", va="bottom", fontsize=8, color=INK)


def quantile_map(ax, pts, col, label, fmt, net, bounds):
    base(ax, net, bounds)
    q = pd.qcut(pts[col], 5, labels=False, duplicates="drop")
    edges = pts[col].quantile([0, .2, .4, .6, .8, 1]).to_numpy()
    for k in range(5):
        sel = pts[q == k]
        ax.scatter(sel.x, sel.y, s=4, c=SEQ[k], linewidths=0, zorder=3 + k)
    handles = [Line2D([], [], marker="o", linestyle="", markersize=6, color=SEQ[k],
                      label=f"{fmt(edges[k])} to {fmt(edges[k + 1])}") for k in range(5)]
    ax.legend(handles=handles, title=label, loc="upper left", frameon=False, fontsize=8, title_fontsize=8)


def hotspot_layer(ax, hs, col):
    cls = hs[col + "_class"]
    ns = hs[cls == ""]
    ax.scatter(ns.x, ns.y, s=2, c=NS, linewidths=0, zorder=3)
    for k, c, z in [("cold", COLD, 4), ("hot", HOT, 5)]:
        sel = hs[cls == k]
        ax.scatter(sel.x, sel.y, s=7, c=c, linewidths=0, zorder=z)
    return int((cls == "hot").sum()), int((cls == "cold").sum())


def main(outdir):
    stops = pd.read_csv(f"{outdir}/table_stop_measures.csv", dtype={"stop_id": str})
    stops = stops[stops.n >= 100]
    hs = pd.read_csv(f"{outdir}/hotspots.csv", dtype={"stop_id": str})
    for c in [c for c in hs.columns if c.endswith("_class")]:
        hs[c] = hs[c].fillna("")
    net = network()
    bounds = (stops.x.min(), stops.y.min(), stops.x.max(), stops.y.max())
    bg = gpd.read_file(D + "bg.gpkg")

    # Map 1 and 2: the two measures by stop
    for col, label, fmt, name, title in [
        ("late_share", "Share of arrivals more than\n5 minutes late", lambda v: f"{100 * v:.0f}%", "map1_late_by_stop",
         "Late arrivals by bus stop"),
        ("mae", "MBTA 5-minute prediction,\nmean absolute error", lambda v: f"{v:.0f} s", "map2_prediction_error_by_stop",
         "Prediction error by bus stop")]:
        fig, ax = plt.subplots(figsize=(8, 8.5))
        quantile_map(ax, stops, col, label, fmt, net, bounds)
        ax.set_title(title, loc="left", fontsize=12, color=INK)
        fig.text(0.01, 0.01, f"Weekdays Sep 28 to Oct 23, 2026, less Oct 12. {len(stops):,} stops with 100 or more arrivals; "
                 "quintiles. Grey lines: MBTA bus routes.", fontsize=7, color=MUTED)
        fig.savefig(f"{outdir}/{name}.png", dpi=200, bbox_inches="tight")
        plt.close(fig)

    # Map 3: hot spots of the raw measures, two panels
    fig, axes = plt.subplots(1, 2, figsize=(14, 8))
    for ax, col, title in [(axes[0], "late_share", "Late arrivals"), (axes[1], "mae", "Prediction error")]:
        base(ax, net, bounds)
        h, c = hotspot_layer(ax, hs, col)
        ax.set_title(f"{title}: {h} hot spots, {c} cold spots", loc="left", fontsize=11, color=INK)
    handles = [Line2D([], [], marker="o", linestyle="", markersize=6, color=HOT, label="Hot spot (high values cluster)"),
               Line2D([], [], marker="o", linestyle="", markersize=6, color=COLD, label="Cold spot (low values cluster)"),
               Line2D([], [], marker="o", linestyle="", markersize=4, color=NS, label="Not significant")]
    axes[0].legend(handles=handles, loc="upper left", frameon=False, fontsize=8)
    fig.suptitle("Getis-Ord Gi* hot spot analysis, 500 m distance band, FDR-corrected at 0.05", x=0.01, ha="left",
                 fontsize=12, color=INK)
    fig.savefig(f"{outdir}/map3_hotspots.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    # Map 4: hot spots of the residual measures (same route, same point along it) over the neighborhood layer
    fig, axes = plt.subplots(1, 2, figsize=(14, 8))
    for ax, col, title in [(axes[0], "late_r", "Late arrivals, relative to route and position"),
                           (axes[1], "err_r", "Prediction error, relative to route and position")]:
        bg[bg.ej_minority & ~bg.ej_income].plot(ax=ax, color=EJ_MINORITY, linewidth=0, zorder=0)
        bg[bg.ej_income].plot(ax=ax, color=EJ_INCOME, linewidth=0, zorder=0)
        base(ax, net, bounds)
        h, c = hotspot_layer(ax, hs, col)
        ax.set_title(f"{title}: {h} hot, {c} cold", loc="left", fontsize=11, color=INK)
    handles = [Line2D([], [], marker="o", linestyle="", markersize=6, color=HOT, label="Hot spot"),
               Line2D([], [], marker="o", linestyle="", markersize=6, color=COLD, label="Cold spot"),
               Line2D([], [], marker="o", linestyle="", markersize=4, color=NS, label="Not significant"),
               Patch(color=EJ_INCOME, label="Block group meets the income criterion"),
               Patch(color=EJ_MINORITY, label="Meets the minority criterion only")]
    axes[0].legend(handles=handles, loc="upper left", frameon=False, fontsize=8)
    fig.suptitle("Hot spots after removing route and position effects, over Environmental Justice block groups",
                 x=0.01, ha="left", fontsize=12, color=INK)
    fig.savefig(f"{outdir}/map4_residual_hotspots_ej.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("maps written")


if __name__ == "__main__":
    main(sys.argv[1])
