"""Fix the rule that assigns each trip the MBTA's headway or timetable standard, from the MBTA's own
September 2026 weekday records (the Fall 2026 timetable started September 6).

Rule: the majority standard of the MBTA's timepoint records for the same route, direction and scheduled hour;
if that cell has no records, the route and direction's majority; then the route's; otherwise timetable
(schedule standard). Writes data/standard_rule.csv and prints how cleanly the cells split.
"""
import zipfile
import numpy as np
import pandas as pd

z = zipfile.ZipFile("data/MBTA_Bus_Arrival_Departure_Times_2026.zip")
m = pd.read_csv(z.open("MBTA_Bus_Arrival_Departure_Times_2026/MBTA-Bus-Arrival-Departure-Times_2026-09.csv"),
                usecols=["service_date", "route_id", "direction_id", "scheduled", "standard_type"], dtype=str, engine="pyarrow")
d = pd.to_datetime(m.service_date)
m = m[(d >= "2026-09-08") & (d.dt.dayofweek < 5)].copy()
m["hour"] = m.scheduled.str[11:13].astype(int)
# MBTA bus GTFS: direction_id 0 is outbound, 1 inbound
m["direction_id"] = m.direction_id.map({"Outbound": 0, "Inbound": 1})
m["headway"] = (m.standard_type == "Headway").astype(float)
cell = m.groupby(["route_id", "direction_id", "hour"]).headway.agg(["mean", "size"]).reset_index()
cell["standard"] = np.where(cell["mean"] >= 0.5, "Headway", "Schedule")
purity = np.average(np.maximum(cell["mean"], 1 - cell["mean"]), weights=cell["size"])
rd = m.groupby(["route_id", "direction_id"]).headway.mean().ge(0.5).map({True: "Headway", False: "Schedule"}).rename("rd_standard")
rt = m.groupby("route_id").headway.mean().ge(0.5).map({True: "Headway", False: "Schedule"}).rename("route_standard")
cell[["route_id", "direction_id", "hour", "standard"]].to_csv("data/standard_rule.csv", index=False)
rd.to_csv("data/standard_rule_route_direction.csv"); rt.to_csv("data/standard_rule_route.csv")
print(f"September weekdays: {m.service_date.nunique()} days, {len(m):,} records, {len(cell):,} route-direction-hour cells")
print(f"share of records agreeing with their cell's majority: {100*purity:.1f}%")
print("cells by standard:", cell.standard.value_counts().to_dict())
for r in ["15", "23", "66"]:
    c = cell[cell.route_id == r]
    print(f"route {r}: headway in {int((c.standard == 'Headway').sum())} of {len(c)} cells")
