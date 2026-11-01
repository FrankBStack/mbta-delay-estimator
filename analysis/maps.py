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
from matplotlib import patheffects
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from shapely import wkt
from shapely.geometry import box

D = "data/"
SEQ = ["#b7d3f6", "#6da7ec", "#2a78d6", "#184f95", "#0d366b"]   # blue ramp, steps 150-700
HOT, COLD = "#e34948", "#2a78d6"
INK, MUTED, GRID, WATER = "#0b0b0b", "#898781", "#d3d2cb", "#e3ecf2"
EJ_INCOME, EJ_MINORITY, GRID_ON_EJ = "#cbcbcb", "#e8e8e8", "#a3a29b"   # greys: no hue shared with the points
HALO = [patheffects.withStroke(linewidth=2.5, foreground="white")]
CITIES = [("Boston", -71.0589, 42.3601), ("Cambridge", -71.1097, 42.3736), ("Newton", -71.1925, 42.3290),
          ("Waltham", -71.2356, 42.3765), ("Dorchester", -71.0620, 42.3016), ("Quincy", -71.0023, 42.2529),
          ("Lynn", -70.9380, 42.4560), ("Salem", -70.8967, 42.5195), ("Hingham", -70.9050, 42.2280)]
# label, lon, lat and an offset in points where the name would otherwise sit on the stops it refers to
CORE_CITIES = [("Downtown", -71.0589, 42.3601, 0, 0), ("Cambridge", -71.1097, 42.3736, 0, 0),
               ("South Boston", -71.0450, 42.3340, 0, 0), ("Roxbury Crossing", -71.0936, 42.3304, -6, -11),
               ("Dorchester", -71.0620, 42.3016, 0, 9)]
# places named in the hot spot paragraphs that are not cities: label, lon, lat, offset in points
PLACES = [("Roxbury Crossing", -71.0936, 42.3304, -22, -30), ("East Boston and Chelsea", -71.0224, 42.3835, 30, 12),
          ("Marblehead", -70.8650, 42.4970, 0, 16)]
CORE = (-71.135, 42.295, -71.030, 42.385)   # inner core shown in each inset
COUNTIES = ["25025", "25017", "25021", "25009", "25023"]   # Suffolk, Middlesex, Norfolk, Essex, Plymouth
plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "axes.edgecolor": GRID, "text.color": INK})


def to_xy(lons, lats):
    return gpd.GeoSeries(gpd.points_from_xy(lons, lats), crs=4326).to_crs(26986)


def layers(bounds):
    shp = pd.read_csv(D + "shapes_bus.csv", dtype={"shape_id": str})
    net = gpd.GeoDataFrame(shp, geometry=shp.wkt.map(wkt.loads), crs=4326).to_crs(26986)
    water = pd.concat([gpd.read_file(f"zip://{D}tiger_water/tl_2024_{c}_areawater.zip") for c in COUNTIES]).to_crs(26986)
    water = water.clip_by_rect(bounds[0] - 5000, bounds[1] - 5000, bounds[2] + 5000, bounds[3] + 5000)
    state = gpd.read_file(f"zip://{D}tiger_water/cb_2023_us_state_500k.zip")
    state = state[state.STUSPS == "MA"].to_crs(26986)
    return net, water[~water.is_empty], state


def base(ax, net, water, bounds, pad=1500, line=GRID, scale_km=5):
    water.plot(ax=ax, color=WATER, linewidth=0, zorder=0.5)
    net.plot(ax=ax, color=line, linewidth=0.5, zorder=1)
    ax.set_xlim(bounds[0] - pad, bounds[2] + pad)
    ax.set_ylim(bounds[1] - pad, bounds[3] + pad)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    for s in ax.spines.values():
        s.set_visible(False)
    x0, y0 = bounds[0] - pad + 0.03 * (bounds[2] - bounds[0]), bounds[1] - pad + 0.03 * (bounds[3] - bounds[1])
    ax.plot([x0, x0 + 1000 * scale_km], [y0, y0], color=INK, linewidth=1.5, zorder=8)
    ax.text(x0 + 500 * scale_km, y0 + 0.012 * (bounds[3] - bounds[1]), f"{scale_km} km", ha="center", va="bottom", fontsize=8,
            color=INK, zorder=8, path_effects=HALO)


def city_labels(ax, cities):
    pts = to_xy([c[1] for c in cities], [c[2] for c in cities])
    for c, p in zip(cities, pts):
        dx, dy = c[3:] or (0, 0)
        ax.annotate(c[0], (p.x, p.y), xytext=(dx, dy), textcoords="offset points", fontsize=7.5, color=INK, zorder=7,
                    ha="right" if dx < 0 else "center", va="top" if dy < 0 else "center", path_effects=HALO)


def place_labels(ax, places):
    pts = to_xy([p[1] for p in places], [p[2] for p in places])
    for (name, _, _, dx, dy), pt in zip(places, pts):
        ax.annotate(name, (pt.x, pt.y), xytext=(dx, dy), textcoords="offset points", fontsize=7.5, color=INK, zorder=7,
                    ha="left" if dx > 0 else "right" if dx < 0 else "center", va="center",
                    arrowprops=dict(arrowstyle="-", color=INK, linewidth=0.6, shrinkA=1, shrinkB=5), path_effects=HALO)


def north_arrow(ax):
    ax.annotate("N", xy=(0.965, 0.975), xytext=(0.965, 0.905), xycoords="axes fraction", textcoords="axes fraction",
                ha="center", va="center", fontsize=9, color=INK, zorder=8,
                arrowprops=dict(arrowstyle="-|>", color=INK, linewidth=1.2))


def locator(ax, state, bounds):
    state.plot(ax=ax, color="#e6e6e6", edgecolor="#9a9a9a", linewidth=0.5)
    ax.add_patch(Rectangle((bounds[0], bounds[1]), bounds[2] - bounds[0], bounds[3] - bounds[1], fill=False, edgecolor=INK, linewidth=0.9))
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("Study area in Massachusetts", fontsize=7.5, color=MUTED, loc="left", pad=2)


def figure():
    """One map: the main panel, an inner-core inset, the locator and a legend column."""
    fig = plt.figure(figsize=(8.5, 7.3))
    gs = fig.add_gridspec(3, 2, width_ratios=[3.1, 1], height_ratios=[1.25, 0.72, 1.0], wspace=0.03, hspace=0.1,
                          left=0.005, right=0.995, top=0.93, bottom=0.045)
    ax, axc, axl, axg = (fig.add_subplot(gs[:, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, 1]), fig.add_subplot(gs[2, 1]))
    axg.set_axis_off()
    return fig, ax, axc, axl, axg


def core_box():
    p = to_xy([CORE[0], CORE[2]], [CORE[1], CORE[3]])
    return (p[0].x, p[0].y, p[1].x, p[1].y)


def draw_core(axc, ax, net, water, draw_points, line=GRID):
    cb = core_box()
    base(axc, net, water, cb, pad=0, line=line, scale_km=1)
    draw_points(axc, 2.6)
    city_labels(axc, CORE_CITIES)
    axc.set_title("Inner core", fontsize=7.5, color=MUTED, loc="left", pad=2)
    for s in axc.spines.values():
        s.set_visible(True)
    ax.add_patch(Rectangle((cb[0], cb[1]), cb[2] - cb[0], cb[3] - cb[1], fill=False, edgecolor=INK, linewidth=0.7, zorder=6))


def quantile_points(pts, col, net, water, label, fmt, title, footer, path, state, bounds):
    q = pd.qcut(pts[col], 5, labels=False, duplicates="drop")
    edges = pts[col].quantile([0, .2, .4, .6, .8, 1]).to_numpy()

    def draw(ax, scale):
        for k in range(5):
            sel = pts[q == k]
            ax.scatter(sel.x, sel.y, s=5 * scale, c=SEQ[k], linewidths=0, zorder=3 + k)

    fig, ax, axc, axl, axg = figure()
    base(ax, net, water, bounds)
    draw(ax, 1)
    city_labels(ax, CITIES)
    north_arrow(ax)
    draw_core(axc, ax, net, water, draw)
    locator(axl, state, bounds)
    handles = [Line2D([], [], marker="o", linestyle="", markersize=6, color=SEQ[k], label=f"{fmt(edges[k])} to {fmt(edges[k + 1])}") for k in range(5)]
    axg.legend(handles=handles, title=label, loc="upper left", frameon=False, fontsize=8, title_fontsize=8, alignment="left")
    fig.suptitle(title, x=0.01, ha="left", fontsize=12, color=INK)
    fig.text(0.01, 0.01, footer, fontsize=7, color=MUTED)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def hotspot_points(hs, col, net, water, title, subtitle, path, state, bounds, bg=None, places=(), line=GRID):
    cls = hs[col + "_class"]

    def draw(ax, scale):
        for k, c, z in [("cold", COLD, 4), ("hot", HOT, 5)]:
            sel = hs[cls == k]
            ax.scatter(sel.x, sel.y, s=9 * scale, c=c, linewidths=0, zorder=z)

    fig, ax, axc, axl, axg = figure()
    for a in (ax, axc):
        if bg is not None:
            bg[bg.ej_minority & ~bg.ej_income].plot(ax=a, color=EJ_MINORITY, linewidth=0, zorder=0)
            bg[bg.ej_income].plot(ax=a, color=EJ_INCOME, linewidth=0, zorder=0)
    base(ax, net, water, bounds, line=line)
    draw(ax, 1)
    city_labels(ax, CITIES)
    place_labels(ax, places)
    north_arrow(ax)
    draw_core(axc, ax, net, water, draw, line=line)
    locator(axl, state, bounds)
    h, c = int((cls == "hot").sum()), int((cls == "cold").sum())
    handles = [Line2D([], [], marker="o", linestyle="", markersize=6, color=HOT, label=f"Hot spot ({h})"),
               Line2D([], [], marker="o", linestyle="", markersize=6, color=COLD, label=f"Cold spot ({c})")]
    if bg is not None:
        handles += [Patch(color=EJ_INCOME, label="Block group meets the\nincome criterion"),
                    Patch(color=EJ_MINORITY, label="Meets the minority\ncriterion only")]
    axg.legend(handles=handles, loc="upper left", frameon=False, fontsize=8, alignment="left", labelspacing=0.9)
    fig.suptitle(title, x=0.01, ha="left", fontsize=12, color=INK)
    fig.text(0.01, 0.01, subtitle, fontsize=7, color=MUTED)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main(outdir):
    stops = pd.read_csv(f"{outdir}/table_stop_measures.csv", dtype={"stop_id": str})
    stops = stops[stops.n >= 100]
    hs = pd.read_csv(f"{outdir}/hotspots.csv", dtype={"stop_id": str})
    for c in [c for c in hs.columns if c.endswith("_class")]:
        hs[c] = hs[c].fillna("")
    bounds = (stops.x.min(), stops.y.min(), stops.x.max(), stops.y.max())
    net, water, state = layers(bounds)
    bg = gpd.read_file(D + "bg.gpkg")
    footer = (f"Weekdays Sep 28 to Oct 23, 2026, less Oct 12. {len(stops):,} stops with 100 or more arrivals; quintiles. "
              "Grey lines: MBTA bus routes.")
    quantile_points(stops, "late_share", net, water, "Share of arrivals more than\n5 minutes late", lambda v: f"{100 * v:.0f}%",
                    "Late arrivals by bus stop", footer, f"{outdir}/map1_late_by_stop.png", state, bounds)
    quantile_points(stops, "mae", net, water, "MBTA 5-minute prediction,\nmean absolute error", lambda v: f"{v:.0f} s",
                    "Prediction error by bus stop", footer, f"{outdir}/map2_prediction_error_by_stop.png", state, bounds)
    gi = "Getis-Ord Gi*, 500 m distance band, FDR-corrected at 0.05. Stops that are not significant are not shown."
    hotspot_points(hs, "late_share", net, water, "Hot spots of late arrivals", gi, f"{outdir}/map3_hotspots_late.png", state, bounds)
    hotspot_points(hs, "mae", net, water, "Hot spots of prediction error", gi, f"{outdir}/map4_hotspots_error.png", state, bounds)
    adj = gi + " Measures are relative to other stops at the same point on the same routes."
    hotspot_points(hs, "late_r", net, water, "Hot spots of late arrivals after removing route and position effects", adj,
                   f"{outdir}/map5_residual_hotspots_late_ej.png", state, bounds, bg=bg, line=GRID_ON_EJ)
    hotspot_points(hs, "err_r", net, water, "Hot spots of prediction error after removing route and position effects", adj,
                   f"{outdir}/map6_residual_hotspots_error_ej.png", state, bounds, bg=bg, places=PLACES, line=GRID_ON_EJ)
    print("maps written")


if __name__ == "__main__":
    main(sys.argv[1])
