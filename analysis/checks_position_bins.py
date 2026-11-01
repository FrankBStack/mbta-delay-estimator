"""Robustness: the within route x direction x position gaps with finer position bins than the nine in analyze.py.

Point estimates only, on weekday arrivals at stops with MIN_N or more; the share is the fraction of arrivals in cells
holding both flagged and unflagged stops.

Usage: python checks_position_bins.py data/arrivals_window1.csv.gz
"""
import sys
import pandas as pd
import analyze as an

a = an.load(sys.argv[1])
w = a[a.day_type == "weekday"]
sb = pd.read_csv(an.D + "stops_bg.csv", dtype={"stop_id": str}).set_index("stop_id")
stops = an.stop_attributes(sb)
n = w.groupby("stop_id").size()
stops = stops[stops.index.isin(n[n >= an.MIN_N].index)]
for name, bins in [("paper (9 bins)", an.POS_BINS), ("2-minute bins", list(range(0, 62, 2)) + [1e9]), ("1-minute bins", list(range(0, 61)) + [1e9])]:
    w2 = w.copy()
    w2["pos_bin"] = pd.cut(w2.sched_s_from_origin / 60, bins, right=False, labels=False)
    U = an.Units(w2, stops)
    ones = U.weights(False)
    for crit in an.CRITERIA:
        out = []
        for m in ["late", "error"]:
            num, den = U.val[m]
            gap, share = an.within_gap(U.cells["route_position"], U.flags[crit], num, den, ones)
            out.append(f"{m} {100 * gap if m == 'late' else gap:+.2f} (share {share:.2f})")
        print(f"{name:14s} {crit:13s} " + "  ".join(out))
