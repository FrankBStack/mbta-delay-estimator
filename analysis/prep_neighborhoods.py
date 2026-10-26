"""Join bus stops and route shapes to block groups.

Inputs (data/): stops.csv, shapes_bus.csv, trips_bus.csv from the tracker;
tl_2024_25_bg/ (TIGER 2024 block groups), acsdt5y2024-b19013.dat (ACS 2020-2024
median household income), ej2020/EJ_POLY.shp (MassGIS 2020 EJ Populations).

Outputs (data/): stops_bg.csv (one row per stop: block group, income, EJ flags),
shapes_ej.csv (share of each shape's length inside EJ areas), bg.gpkg (block
groups with income and EJ flags, for maps).
"""
import geopandas as gpd
import pandas as pd
from shapely import wkt

SRID = 26986
D = "data/"

# Block groups with income. ACS reports -666666666 where income is suppressed.
bg = gpd.read_file(D + "tl_2024_25_bg/tl_2024_25_bg.shp").to_crs(SRID)
acs = pd.read_csv(D + "acsdt5y2024-b19013.dat", sep="|", dtype=str)
acs = acs[acs.GEO_ID.str.startswith("1500000US25")].copy()
acs["GEOID"] = acs.GEO_ID.str[9:]
acs["mhhi"] = pd.to_numeric(acs.B19013_E001, errors="coerce")
acs["mhhi_moe"] = pd.to_numeric(acs.B19013_M001, errors="coerce")
acs.loc[acs.mhhi < 0, ["mhhi", "mhhi_moe"]] = None
bg = bg[["GEOID", "ALAND", "geometry"]].merge(acs[["GEOID", "mhhi", "mhhi_moe"]], on="GEOID", how="left")

# EJ polygons: flags per criterion. EJ_CRITERI holds the codes (I, M, E and combinations).
ej = gpd.read_file(D + "ej2020/EJ_POLY.shp").to_crs(SRID)
ej["ej_income"] = ej.EJ_CRITERI.str.contains("I")
ej["ej_minority"] = ej.EJ_CRITERI.str.contains("M")
ej["ej_english"] = ej.EJ_CRITERI.str.contains("E")
ej = ej[["GEOID", "MUNICIPALI", "EJ_CRITERI", "BG_MHHI", "PCT_MINORI", "ej_income", "ej_minority", "ej_english", "geometry"]]
ej = ej.rename(columns={"GEOID": "ej_geoid", "MUNICIPALI": "town"})

flags = ej.drop(columns="geometry").groupby("ej_geoid")[["ej_income", "ej_minority", "ej_english"]].any()
bg = bg.merge(flags, left_on="GEOID", right_index=True, how="left")
for c in ["ej_income", "ej_minority", "ej_english"]:
    bg[c] = bg[c].fillna(False).astype(bool)
bg["ej_any"] = bg.ej_income | bg.ej_minority | bg.ej_english
bg.to_file(D + "bg.gpkg", driver="GPKG")

# Stops: income from the block group they fall in, EJ flags from the EJ polygon they fall in.
stops = pd.read_csv(D + "stops.csv", dtype={"stop_id": str})
pts = gpd.GeoDataFrame(stops, geometry=gpd.points_from_xy(stops.lon, stops.lat), crs=4326).to_crs(SRID)
pts = gpd.sjoin(pts, bg[["GEOID", "mhhi", "mhhi_moe", "geometry"]], how="left", predicate="within").drop(columns="index_right")
pts = gpd.sjoin(pts, ej, how="left", predicate="within").drop(columns="index_right")
pts = pts[~pts.index.duplicated()]
for c in ["ej_income", "ej_minority", "ej_english"]:
    pts[c] = pts[c].fillna(False).astype(bool)
pts["ej_any"] = pts.ej_income | pts.ej_minority | pts.ej_english
pts["x"] = pts.geometry.x
pts["y"] = pts.geometry.y
pts.drop(columns="geometry").to_csv(D + "stops_bg.csv", index=False)

# Shapes: share of each route shape's length inside EJ areas, by criterion.
shp = pd.read_csv(D + "shapes_bus.csv", dtype={"shape_id": str})
lines = gpd.GeoDataFrame(shp, geometry=shp.wkt.map(wkt.loads), crs=4326).to_crs(SRID)
lines["len_m"] = lines.length
for c in ["ej_any", "ej_income", "ej_minority"]:
    sel = ej if c == "ej_any" else ej[ej[c]]
    area = sel.geometry.union_all()
    lines[c + "_share"] = lines.geometry.intersection(area).length / lines.len_m
lines.drop(columns=["geometry", "wkt"]).to_csv(D + "shapes_ej.csv", index=False)

print(f"block groups {len(bg)}, with income {bg.mhhi.notna().sum()}, EJ any {bg.ej_any.sum()}, "
      f"income {bg.ej_income.sum()}, minority {bg.ej_minority.sum()}")
print(f"stops {len(pts)}, in a block group {pts.GEOID.notna().sum()}, EJ any {pts.ej_any.sum()}, "
      f"income {pts.ej_income.sum()}, minority {pts.ej_minority.sum()}")
print(f"shapes {len(lines)}, median EJ share {lines.ej_any_share.median():.2f}")

# --- Race and ethnicity (ACS 2020-2024, B03002) and the FTA Title VI minority rule ---
# A block group is a minority area if its minority share exceeds the service area's; a route is a
# minority route if at least a third of its (trip-weighted) length runs through minority areas.
race = pd.read_csv(D + "acsdt5y2024-b03002.dat", sep="|", dtype=str)
race = race[race.GEO_ID.str.startswith("1500000US25")].copy()
race["GEOID"] = race.GEO_ID.str[9:]
for c, col in [("pop", "B03002_E001"), ("nh_white", "B03002_E003"), ("nh_black", "B03002_E004"), ("hispanic", "B03002_E012")]:
    race[c] = pd.to_numeric(race[col], errors="coerce")
race = race[["GEOID", "pop", "nh_white", "nh_black", "hispanic"]]
bg2 = bg.merge(race, on="GEOID", how="left")
bg2["minority_share"] = 1 - bg2.nh_white / bg2["pop"]
bg2["black_share"] = bg2.nh_black / bg2["pop"]
bg2["hispanic_share"] = bg2.hispanic / bg2["pop"]

# service area: block groups within 400 m of a stop that had a bus arrival in the study window
served = pd.read_csv(D + "arrivals_window1.csv.gz", usecols=["stop_id"], dtype={"stop_id": str}, engine="pyarrow").stop_id.unique()
sp = pts[pts.stop_id.isin(served)]
near = gpd.sjoin(bg2[["GEOID", "geometry"]], gpd.GeoDataFrame(geometry=sp.geometry.buffer(400), crs=SRID), predicate="intersects")
svc = bg2[bg2.GEOID.isin(near.GEOID.unique()) & (bg2["pop"] > 0)]
svc_share = 1 - svc.nh_white.sum() / svc["pop"].sum()
bg2["fta_minority"] = bg2.minority_share > svc_share
bg2[["GEOID", "pop", "minority_share", "black_share", "hispanic_share", "fta_minority"]].to_csv(D + "bg_race.csv", index=False)

stops2 = pd.read_csv(D + "stops_bg.csv", dtype={"stop_id": str, "GEOID": str, "ej_geoid": str})
stops2 = stops2.drop(columns=[c for c in ["minority_share", "black_share", "hispanic_share", "fta_minority"] if c in stops2])
stops2 = stops2.merge(bg2[["GEOID", "minority_share", "black_share", "hispanic_share", "fta_minority"]], on="GEOID", how="left")
stops2["fta_minority"] = stops2.fta_minority.fillna(False).astype(bool)
stops2.to_csv(D + "stops_bg.csv", index=False)

fta_area = bg2[bg2.fta_minority].geometry.union_all()
lines["fta_minority_share"] = lines.geometry.intersection(fta_area).length / lines.len_m
lines.drop(columns=["geometry", "wkt"]).to_csv(D + "shapes_ej.csv", index=False)
print(f"service area: {len(svc)} block groups, minority share {svc_share:.3f}; FTA minority block groups {bg2.fta_minority.sum()}; "
      f"stops flagged {stops2.fta_minority.sum()}")

# --- Timepoints, from the MBTA GTFS zip (data/MBTA_GTFS.zip) ---
import zipfile
with zipfile.ZipFile(D + "MBTA_GTFS.zip") as z:
    tr = pd.read_csv(z.open("trips.txt"), usecols=["trip_id", "route_id"], dtype=str)
    rt = pd.read_csv(z.open("routes.txt"), usecols=["route_id", "route_type"], dtype={"route_id": str})
    bus_trips = set(tr[tr.route_id.isin(rt[rt.route_type == 3].route_id)].trip_id)
    # the MBTA marks bus timepoints with checkpoint_id; its timepoint column flags little beyond trip origins
    st = pd.read_csv(z.open("stop_times.txt"), usecols=["trip_id", "stop_sequence", "checkpoint_id"],
                     dtype={"trip_id": str, "stop_sequence": "int64", "checkpoint_id": str}, engine="pyarrow")
st = st[st.trip_id.isin(bus_trips)]
st["timepoint"] = st.checkpoint_id.notna().astype(float)
st = st[["trip_id", "stop_sequence", "timepoint"]]
st.to_csv(D + "timepoints.csv", index=False)
print(f"timepoints: {len(st)} bus stop times, {int((st.timepoint == 1).sum())} marked as timepoints")
