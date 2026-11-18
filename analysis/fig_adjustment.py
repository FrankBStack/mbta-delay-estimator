"""Dot-and-interval figure of the gaps at each level of adjustment.
Usage: python fig_adjustment.py output/window1_v2"""
import sys
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

o = sys.argv[1].rstrip("/") + "/"
est = pd.read_csv(o + "table_estimates.csv")
com = pd.read_csv(o + "table_common_sample.csv")

INK, MUTED, GRID = "#222222", "#555555", "#d9d9d9"
plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "text.color": INK,
                     "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": INK})

CRITERIA = [("ej_income", "Income-flagged"), ("ej_minority", "State-minority-flagged"),
            ("fta_minority", "Federal-minority-flagged")]
MEASURES = [("late", 100, "Late arrivals (percentage points)"), ("error", 1, "Prediction error (seconds)")]
LEVELS = ["All stops", "Comparable stops", "Within route", "Within route\nand position"]


def rows(crit, measure):
    a = est[(est.kind == "gap") & (est["var"] == crit) & (est.measure == measure) & (est.level == "none")].iloc[0]
    out = [(a.estimate, a.ci_lo, a.ci_hi)]
    for col in ["none", "route", "route_position"]:
        c = com[(com.criterion == crit) & (com.measure == measure) & (com.column == col)].iloc[0]
        out.append((c.estimate, c.ci_lo, c.ci_hi))
    return out


fig, axes = plt.subplots(2, 3, figsize=(6.5, 3.9), sharey=True, sharex="row")
for i, (measure, scale, xlabel) in enumerate(MEASURES):
    for j, (crit, name) in enumerate(CRITERIA):
        ax = axes[i, j]
        ax.axvline(0, color=MUTED, lw=0.8, zorder=1)
        for y, (e, lo, hi) in enumerate(rows(crit, measure)):
            ax.plot([lo * scale, hi * scale], [y, y], color=INK, lw=1.2, solid_capstyle="butt", zorder=2)
            ax.plot(e * scale, y, "o", color=INK, ms=5, zorder=3)
        ax.set_yticks(range(4), LEVELS)
        ax.set_ylim(3.5, -0.5)
        ax.tick_params(length=0)
        ax.grid(axis="x", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        for s in ax.spines.values():
            s.set_visible(False)
        if i == 0:
            ax.set_title(name, fontsize=9, color=INK, pad=6)
        if j == 1:
            ax.set_xlabel(xlabel)
    lim = max(abs(v) for v in axes[i, 0].get_xlim())
    axes[i, 0].set_xlim(-lim, lim)
fig.tight_layout(h_pad=1.6, w_pad=1.2)
fig.savefig(o + "fig_adjustment.png", dpi=255)
