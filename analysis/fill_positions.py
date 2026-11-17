"""Fill missing scheduled positions (sched_s_from_origin) in an export, in place, from the MBTA timetable version
in effect each day. The live database holds only the current timetable, so visits on trips the MBTA has since
dropped come out of the export without one. Rows that already have a position are checked against the archive.

Usage: python fill_positions.py data/visits_window2.csv.gz     (after fetch_gtfs_archive.py)
"""
import os
import sys
import zipfile
import pandas as pd
import analyze as an

ARCHIVE = an.D + "gtfs_archive/"
path = sys.argv[1]
v = pd.read_csv(path, dtype=str, engine="pyarrow")
feeds = pd.read_csv(ARCHIVE + "archived_feeds.txt", dtype=str)
ymd = v.start_date.str.replace("-", "")
days = pd.Series(sorted(ymd.unique()))
version = days.map(lambda d: feeds[(feeds.feed_start_date <= d) & (feeds.feed_end_date >= d)].feed_start_date.iloc[0])
v["_version"] = ymd.map(dict(zip(days, version)))


def seconds(t):
    p = t.str.split(":", expand=True).astype(int)
    return p[0] * 3600 + p[1] * 60 + p[2]


pos = []
for ver in sorted(v._version.unique()):
    trips = set(v.loc[v._version == ver, "trip_id"])
    st = pd.read_csv(zipfile.ZipFile(f"{ARCHIVE}{ver}.zip").open("stop_times.txt"), dtype=str,
                     usecols=["trip_id", "stop_sequence", "arrival_time", "departure_time"])
    st = st[st.trip_id.isin(trips)].dropna(subset=["arrival_time", "departure_time"])
    st["seq"] = st.stop_sequence.astype(int)
    origin = seconds(st.loc[st.groupby("trip_id").seq.idxmin()].set_index("trip_id").departure_time)
    st["_pos"] = seconds(st.arrival_time) - st.trip_id.map(origin)
    pos.append(st[["trip_id", "stop_sequence", "_pos"]].assign(_version=ver))
v = v.merge(pd.concat(pos), on=["_version", "trip_id", "stop_sequence"], how="left")

had = v.sched_s_from_origin.notna()
agree = (v.sched_s_from_origin[had].astype(float) == v._pos[had]).mean()
fill = ~had & v._pos.notna()
print(f"{len(v):,} rows; {had.sum():,} had a position ({agree:.2%} equal to the archive's); "
      f"{fill.sum():,} filled; {(~had & ~fill).sum():,} still without one")
print(v[fill].groupby("start_date").size().to_string() if fill.any() else "nothing to fill")
v.loc[fill, "sched_s_from_origin"] = v._pos[fill].astype(int).astype(str)
v.drop(columns=["_version", "_pos"]).to_csv(path + ".tmp", index=False, compression="gzip")
os.replace(path + ".tmp", path)
