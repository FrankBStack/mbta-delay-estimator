"""Download the MBTA's archived GTFS versions in effect on any day from FIRST to LAST into data/gtfs_archive/.

Usage: python fetch_gtfs_archive.py 2026-10-26 2026-11-20
"""
import pathlib
import sys
import urllib.request
import pandas as pd

LIST = "https://cdn.mbta.com/archive/archived_feeds.txt"
out = pathlib.Path("data/gtfs_archive")
out.mkdir(parents=True, exist_ok=True)
first, last = (int(pd.Timestamp(d).strftime("%Y%m%d")) for d in sys.argv[1:3])
urllib.request.urlretrieve(LIST, out / "archived_feeds.txt")
feeds = pd.read_csv(out / "archived_feeds.txt", dtype={"feed_start_date": int, "feed_end_date": int})
need = feeds[(feeds.feed_start_date <= last) & (feeds.feed_end_date >= first)]
for f in need.itertuples():
    dest = out / f"{f.feed_start_date}.zip"
    if not dest.exists():
        urllib.request.urlretrieve(f.archive_url, dest)
    print(f"{f.feed_start_date}-{f.feed_end_date}  {f.feed_version}  {dest}")
