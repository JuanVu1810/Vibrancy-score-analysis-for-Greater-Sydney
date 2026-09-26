"""Transport for NSW sources: GTFS stops and traffic lights.

The files are saved by download_data.py: the GTFS zip through the TfNSW API (or the public link), and the traffic lights
spreadsheet from the Data.NSW catalogue (saved by hand if the site blocks scripts).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from shapely.geometry import Point

from ..core import AU_BBOX, NSW_BBOX, EtlError, Snapshot, Source, error, to_int, warn


def _points(lon, lat, box, ids, snap):
    """Point geometries for the rows whose coordinates are present, non-zero and inside `box`.

    A few rows in each TfNSW file have typos (a latitude of 30 instead of -30, a longitude of 1501
    instead of 151, 0,0). They are kept with an empty geometry rather than guessed at, and their ids
    are recorded in the manifest. Returns (geometry array, boolean Series of the bad rows).
    """
    ok = (lon.notna() & lat.notna() & (lon != 0) & (lat != 0)
          & (lon > box[0]) & (lon < box[2]) & (lat > box[1]) & (lat < box[3]))
    pts = np.array(gpd.points_from_xy(lon.fillna(0).to_numpy(), lat.fillna(0).to_numpy()), dtype=object)
    pts[~ok.to_numpy()] = None
    bad = ~ok
    snap.extra.update(invalid_coordinates=int(bad.sum()),
                      invalid_examples=[{"id": str(i), "lat": None if pd.isna(la) else float(la),
                                         "lon": None if pd.isna(lo) else float(lo)}
                                        for i, la, lo in list(zip(ids[bad], lat[bad], lon[bad]))[:20]])
    return pts, bad


def _check_placed(gdf, label: str) -> list:
    missing = int(gdf.geometry.isna().sum())
    if not missing:
        return []
    if missing > 0.01 * len(gdf):
        return [error(f"{missing} of {len(gdf)} {label} have unusable coordinates")]
    return [warn(f"{missing} {label} have unusable coordinates and are kept with an empty geometry (their ids are in the manifest)")]


def _stops_from_folder(folder: Path) -> list:
    """Every stops.txt in an unzipped GTFS download (some bundles hold one zip per mode, unzipped inside it)."""
    return [pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8-sig")
            for f in sorted(folder.rglob("*")) if f.is_file() and f.name.lower() == "stops.txt"]


def _feed_release(folder: Path) -> str | None:
    for f in sorted(folder.rglob("*")):
        if f.is_file() and f.name.lower() == "feed_info.txt":
            info = pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8-sig")
            if len(info):
                row = info.iloc[0]
                return "feed " + " ".join(str(row[c]) for c in ("feed_version", "feed_start_date")
                                          if c in info.columns and row[c])
    return None


def parse_stops(snap: Snapshot) -> dict:
    folder = snap.unzip()
    frames = _stops_from_folder(folder)
    if not frames:
        raise EtlError(f"no stops.txt found in {snap.files['main']['path']}")
    raw = pd.concat(frames, ignore_index=True).drop_duplicates("stop_id").reset_index(drop=True)
    lat = pd.to_numeric(raw["stop_lat"], errors="coerce")
    lon = pd.to_numeric(raw["stop_lon"], errors="coerce")
    geom, _ = _points(lon, lat, AU_BBOX, raw["stop_id"], snap)

    def text(col):  # a column as text, empty strings as NULL, or all NULL if the feed lacks it
        return raw[col].where(raw[col] != "", None) if col in raw else pd.Series([None] * len(raw))

    df = pd.DataFrame({"stop_id": raw["stop_id"], "stop_code": text("stop_code"), "stop_name": raw["stop_name"]})
    # GTFS: a blank location_type means 0, an ordinary stop or platform (1 is a station).
    df["location_type"] = pd.array([to_int(v) or 0 for v in (raw["location_type"] if "location_type" in raw else [""] * len(raw))],
                                   dtype="Int64")
    df["parent_station"] = text("parent_station")
    df["wheelchair_boarding"] = pd.array([to_int(v) for v in (raw["wheelchair_boarding"] if "wheelchair_boarding" in raw else [""] * len(raw))],
                                         dtype="Int64")
    df["platform_code"] = text("platform_code")
    snap.release = _feed_release(folder) or f"retrieved {snap.retrieved_at[:10]}"
    snap.extra.update(stops=len(df), stations=int((df["location_type"] == 1).sum()))
    return {"stops": gpd.GeoDataFrame(df, geometry=geom, crs=4326).rename_geometry("geom")}


def check_stops(out: dict, ctx) -> list:
    gdf, issues = out["stops"], []
    if len(gdf) < 10_000:
        issues.append(error(f"only {len(gdf)} stops"))
    if gdf["stop_id"].duplicated().any():
        issues.append(error("duplicate stop ids"))
    issues += _check_placed(gdf, "stops")
    if not (gdf["location_type"] == 1).any():
        issues.append(warn("no station rows (location_type 1) in the feed"))
    return issues


# =============================================================================================
# Traffic lights
# =============================================================================================
_ASSET = {"veh": "Vehicle", "vehicle": "Vehicle", "ped": "Pedestrian", "pedestrian": "Pedestrian"}
_SYNONYMS = {"lon": "longitude", "long": "longitude", "x": "longitude", "lat": "latitude", "y": "latitude"}


def _snake(name) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip()).strip("_").lower()
    return _SYNONYMS.get(s, s)


def _read_lights(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        df.columns = [_snake(c) for c in df.columns]
        return df
    wb = load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        for i, r in enumerate(rows[:25]):
            names = {_snake(c) for c in r if c is not None}
            if {"latitude", "longitude"} <= names:
                cols = [_snake(c) if c is not None else f"col{j}" for j, c in enumerate(r)]
                body = [["" if v is None else v for v in row] for row in rows[i + 1:] if any(v is not None for v in row)]
                return pd.DataFrame(body, columns=cols)
    raise EtlError(f"{path.name}: no sheet with 'Latitude' and 'Longitude' columns")


def parse_lights(snap: Snapshot) -> dict:
    raw = _read_lights(snap.path())
    raw = raw.loc[:, ~raw.columns.duplicated()]
    for col in raw.columns:
        if raw[col].dtype == object:
            raw[col] = raw[col].map(lambda v: v.strip() if isinstance(v, str) else v)  # e.g. 'SYDNEY ' -> 'SYDNEY'
    if "asset_type" in raw.columns:  # releases differ: VEH/PED (2021) and Vehicle/Pedestrian (2026)
        raw["asset_type"] = raw["asset_type"].map(lambda v: _ASSET.get(str(v).strip().lower(), v))
    if "date_install" in raw.columns and raw["date_install"].map(lambda v: isinstance(v, (datetime, date))).any():
        raw["date_install"] = pd.to_datetime(
            raw["date_install"].map(lambda v: v if isinstance(v, (datetime, date)) else pd.NaT), errors="coerce")
    lon = pd.to_numeric(raw["longitude"], errors="coerce")
    lat = pd.to_numeric(raw["latitude"], errors="coerce")
    ids = raw["equipment_id"] if "equipment_id" in raw.columns else pd.Series(range(len(raw)))
    geom, _ = _points(lon, lat, NSW_BBOX, ids, snap)
    df = raw.drop(columns=["longitude", "latitude"]).reset_index(drop=True)
    for col in df.columns:  # empty strings become NULL
        if df[col].dtype == object:
            df[col] = df[col].where(df[col].astype(str) != "", None)
    snap.extra.update(rows=len(df), columns=list(df.columns))
    return {"traffic_lights": gpd.GeoDataFrame(df, geometry=geom, crs=4326).rename_geometry("geom")}


def check_lights(out: dict, ctx) -> list:
    gdf, issues = out["traffic_lights"], []
    if len(gdf) < 3000:
        issues.append(error(f"only {len(gdf)} traffic lights"))
    issues += _check_placed(gdf, "traffic lights")
    if "asset_type" not in gdf.columns:
        issues.append(warn("no asset_type column, so pedestrian and vehicle signals can't be told apart"))
    return issues


SOURCES = [
    Source("gtfs_stops", "TfNSW Timetables Complete GTFS (stops.txt)", "CC BY (TfNSW Open Data)",
           "Transport for NSW", ("stops",), parse_stops, check_stops),
    Source("traffic_lights", "TfNSW Traffic Lights Location", "CC BY (Data.NSW)", "Transport for NSW",
           ("traffic_lights",), parse_lights, check_lights),
]
