"""Summarize analyze.py's output as results.md. Usage: python write_results.py output/window1"""
import sys, json
import pandas as pd

o = sys.argv[1].rstrip("/") + "/"
g = pd.read_csv(o + "table_gaps.csv"); s = pd.read_csv(o + "table_data_summary.csv")
p = pd.read_csv(o + "table_position.csv", index_col=0); q = pd.read_csv(o + "table_income_quintiles.csv")
r = json.load(open(o + "results.json"))


def row(level, crit, outcome, min_n=100):
    x = g[(g.level == level) & (g.criterion == crit) & (g.outcome == outcome) & ((g.min_n == min_n) | g.min_n.isna())].iloc[0]
    if outcome == "late_share":
        return f"{100*x.gap:+.1f} points ({100*x.ci_lo:+.1f} to {100*x.ci_hi:+.1f})", int(x.n_flagged), int(x.n_unflagged)
    return f"{x.gap:+.1f} s ({x.ci_lo:+.1f} to {x.ci_hi:+.1f})", int(x.n_flagged), int(x.n_unflagged)


W = "stop, within route and position"
L = ["# Results\n",
     "Bus arrivals logged by the tracker. A late arrival is more than 300 s after the scheduled time; prediction error is "
     "the absolute error of the MBTA's prediction issued five minutes before arrival. Gaps are flagged minus unflagged; "
     "95% intervals in parentheses come from 2,000 bootstrap resamples of service days (stop level) or routes (route level).\n",
     "## Data\n", s.to_markdown(index=False) + "\n",
     f"Stops with weekday arrivals: {r['stops_total']}; kept with 100 or more: {r['stops_kept']}. Of kept stops, "
     f"{r['kept_pct_ej_income']:.1f}% are in block groups meeting the income criterion and {r['kept_pct_ej_minority']:.1f}% the minority criterion.\n",
     "## Position along the route (the confounder)\n", p.to_markdown() + "\n",
     "## Hypothesis 1: route level\n",
     "A route is flagged when at least one third of its length (trip-weighted) runs through flagged block groups.\n",
     "| Criterion | Routes flagged / not | Late share gap | Prediction error gap |", "|---|---|---|---|"]
for crit, name in [("ej_income", "Income"), ("ej_minority", "Minority")]:
    a, nf, nu = row("route", crit, "late_share"); b, _, _ = row("route", crit, "mae")
    L.append(f"| {name} | {nf} / {nu} | {a} | {b} |")
L += ["\n## Hypotheses 2 and 3: stops within the same route at the same point along it\n",
      "| Criterion | Stops flagged / not | Late share gap | Prediction error gap |", "|---|---|---|---|"]
for crit, name in [("ej_income", "Income"), ("ej_minority", "Minority")]:
    a, nf, nu = row(W, crit, "late_share"); b, _, _ = row(W, crit, "mae")
    L.append(f"| {name} | {nf} / {nu} | {a} | {b} |")
L += ["\nThe same comparison without the route and position control (raw stop means):\n",
      "| Criterion | Stops flagged / not | Late share gap | Prediction error gap |", "|---|---|---|---|"]
for crit, name in [("ej_income", "Income"), ("ej_minority", "Minority")]:
    a, nf, nu = row("stop, raw", crit, "late_share"); b, _, _ = row("stop, raw", crit, "mae")
    L.append(f"| {name} | {nf} / {nu} | {a} | {b} |")
L += ["\nSensitivity of the within-route gaps to the minimum arrivals per stop:\n",
      "| Minimum | Income, late | Income, error | Minority, late | Minority, error |", "|---|---|---|---|---|"]
for m in [50, 100, 200]:
    L.append(f"| {m} | {row(W,'ej_income','late_share',m)[0]} | {row(W,'ej_income','mae',m)[0]} | "
             f"{row(W,'ej_minority','late_share',m)[0]} | {row(W,'ej_minority','mae',m)[0]} |")
q2 = q.copy(); q2["late_share"] = (100 * q2.late_share).round(1); q2["late_resid"] = (100 * q2.late_resid).round(2)
L += ["\n## Income as a gradient (block group median household income, ACS 2020-2024)\n", q2.round(2).to_markdown(index=False) + "\n",
      f"Spearman correlation of stop residuals with income: late share {r['spearman_income_late_resid']:+.3f}, "
      f"prediction error {r['spearman_income_err_resid']:+.3f}.\n",
      "## Hot spots (Getis-Ord Gi*, 500 m band, FDR 0.05)\n",
      "| Measure | Hot stops | % income-flagged | % minority-flagged | Cold stops | % income | % minority | Routes with most hot stops |",
      "|---|---|---|---|---|---|---|---|"]
for c, name in [("late_share", "Late share, raw"), ("mae", "Prediction error, raw"),
                ("late_r", "Late share, residual"), ("err_r", "Prediction error, residual")]:
    top = ", ".join(f"{k} ({v})" for k, v in list(r[c + "_hot_top_routes"].items())[:4])
    L.append(f"| {name} | {r[c+'_hot_stops']} | {r[c+'_hot_pct_ej_income']:.0f}% | {r[c+'_hot_pct_ej_minority']:.0f}% | {r[c+'_cold_stops']} | "
             f"{r[c+'_cold_pct_ej_income']:.0f}% | {r[c+'_cold_pct_ej_minority']:.0f}% | {top} |")
L.append(f"\nBaseline: {r['kept_pct_ej_income']:.0f}% of kept stops are income-flagged and {r['kept_pct_ej_minority']:.0f}% minority-flagged.\n")
open(o + "results.md", "w").write("\n".join(L))
print("\n".join(L))
