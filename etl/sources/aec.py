"""Australian Electoral Commission: polling places for a federal election."""
from __future__ import annotations

import re

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from ..core import NSW_BBOX, Snapshot, Source, error, inside, to_int, warn

# The election's event id, used in the release name: 31496 is the 2025 federal election.
EVENT_ID = 31496
URL = f"https://results.aec.gov.au/{EVENT_ID}/Website/Downloads/GeneralPollingPlacesDownload-{EVENT_ID}.csv"

_RENAME = {"State": "state", "DivisionID": "division_id", "DivisionNm": "division_name",
           "PollingPlaceID": "polling_place_id", "PollingPlaceTypeID": "polling_place_type_id",
           "PollingPlaceNm": "polling_place_name", "PremisesNm": "premises_name",
           "PremisesAddress1": "premises_address_1", "PremisesAddress2": "premises_address_2",
           "PremisesAddress3": "premises_address_3", "PremisesSuburb": "premises_suburb",
           "PremisesPostCode": "premises_post_code"}
_INT = ["division_id", "polling_place_id", "polling_place_type_id", "premises_post_code"]


def parse(snap: Snapshot) -> dict:
    path = snap.path()
    with open(path, encoding="utf-8-sig") as f:
        title = f.readline()  # the first line is a title, not the header
    m = re.search(r"^(.*?)\s*\[.*Generated:(\d{4}-\d{2}-\d{2})", title)
    if m:
        snap.release = f"{m.group(1)} (event {EVENT_ID}), generated {m.group(2)}"
    raw = pd.read_csv(path, skiprows=1, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    raw = raw[raw["State"] == "NSW"].reset_index(drop=True)
    lat = pd.to_numeric(raw["Latitude"], errors="coerce")
    lon = pd.to_numeric(raw["Longitude"], errors="coerce")
    df = raw.rename(columns=_RENAME)[list(_RENAME.values())].copy()
    for col in _INT:
        df[col] = pd.array([to_int(v) for v in df[col]], dtype="Int64")
    # Places without usable coordinates (blank, or 0,0 as a placeholder) are kept with an empty geometry.
    unplaced = lat.isna() | lon.isna() | (lat == 0) | (lon == 0)
    geom = [None if bad else Point(x, y) for bad, x, y in zip(unplaced, lon, lat)]
    snap.extra.update(nsw_rows=len(df), without_coordinates=int(unplaced.sum()))
    return {"polling_places": gpd.GeoDataFrame(df, geometry=geom, crs=4326).rename_geometry("geom")}


def check(out: dict, ctx) -> list:
    gdf, issues = out["polling_places"], []
    if len(gdf) < 2500:
        issues.append(error(f"only {len(gdf)} NSW polling places"))
    if gdf["polling_place_id"].duplicated().any():
        issues.append(error("duplicate polling place ids"))
    located = gdf[gdf.geometry.notna()]
    if len(located) and not inside(located.total_bounds, NSW_BBOX):
        issues.append(error(f"polling places fall outside NSW: {located.total_bounds}"))
    missing = int(gdf.geometry.isna().sum())
    if missing:
        issues.append(warn(f"{missing} polling places have no usable coordinates (blank or 0,0) and are kept with an empty geometry"))
    return issues


SOURCES = [
    Source("polling_places", "AEC federal election polling places", "not verified (AEC)",
           "Australian Electoral Commission", ("polling_places",), parse, check),
]
