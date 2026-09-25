"""Transport for NSW sources: GTFS stops and traffic lights.

Both come from the TfNSW Open Data Hub. Its website sometimes refuses scripted downloads (it did for
hours on 25 Sep 2026, then stopped), so each source tries its routes in order and says what to do if all fail:

  GTFS stops:      the API with TFNSW_API_KEY (register free at https://opendata.transport.nsw.gov.au),
                   then the public download link, then a zip saved into raw/manual/gtfs/.
  Traffic lights:  the file listed in the Data.NSW catalogue, then a file saved into raw/manual/traffic_lights/.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from openpyxl import load_workbook
from shapely.geometry import Point

from ..core import (AU_BBOX, MANUAL, NSW_BBOX, EtlError, MissingCredential, Snapshot, Source, error,
                    to_int, warn)

GTFS_API = "https://api.transport.nsw.gov.au/v1/publictransport/timetables/complete/gtfs"
GTFS_PAGE = "https://opendata.transport.nsw.gov.au/dataset/timetables-complete-gtfs"
GTFS_CKAN = "https://opendata.transport.nsw.gov.au/data/api/3/action/package_show"
GTFS_PORTAL_ZIP = ("https://opendata.transport.nsw.gov.au/data/dataset/d1f68d4f-b778-44df-9823-cf2fa922e47f/"
                   "resource/67974f14-01bf-47b7-bfa5-c7f2f8a950ca/download/full_greater_sydney_gtfs_static_0.zip")
LIGHTS_PAGE = "https://www.data.nsw.gov.au/data/dataset/2-traffic-lights-location"
LIGHTS_CKAN = "https://data.nsw.gov.au/data/api/3/action/package_show"
LIGHTS_DATASET = "2-traffic-lights-location"

_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"


def _newest(folder: Path, patterns: tuple) -> Path | None:
    files = [p for pat in patterns for p in folder.glob(pat)] if folder.exists() else []
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


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


# =============================================================================================
# GTFS stops
# =============================================================================================
def _portal_gtfs_url(ctx) -> str:
    """The current 'GTFS Timetables Complete' zip from the portal catalogue (the last known link if it can't be read)."""
    try:
        r = ctx.get(GTFS_CKAN, params={"id": "timetables-complete-gtfs"})
        r.raise_for_status()
        return next(x["url"] for x in r.json()["result"]["resources"]
                    if x["url"].lower().endswith(".zip") and "gtfs" in x["url"].lower())
    except (requests.RequestException, ValueError, KeyError, StopIteration):
        return GTFS_PORTAL_ZIP


def fetch_stops(ctx) -> Snapshot:
    key = os.environ.get("TFNSW_API_KEY", "").strip()
    tried = []
    if key:  # the documented programmatic route; the key is sent as a header and never recorded
        try:
            rec = ctx.download("gtfs_stops", "main", GTFS_API, filename="complete_gtfs.zip",
                               headers={"Authorization": f"apikey {key}", "Accept": "application/octet-stream"})
            return Snapshot("gtfs_stops", "unknown", GTFS_API, {"main": rec})
        except EtlError as e:
            tried.append(f"API: {e}")
            ctx.log("  gtfs_stops: the API route failed, trying the public download link")
    url = _portal_gtfs_url(ctx)
    try:
        rec = ctx.download("gtfs_stops", "main", url, filename=url.rsplit("/", 1)[-1])
        return Snapshot("gtfs_stops", "unknown", url, {"main": rec})
    except EtlError as e:
        tried.append(f"portal link: {e}")
    manual = _newest(MANUAL / "gtfs", ("*.zip",))
    if manual:
        rec = ctx.adopt("gtfs_stops", "main", manual)
        return Snapshot("gtfs_stops", "unknown", rec["url"], {"main": rec})
    raise MissingCredential(
        "gtfs_stops could not be downloaded (" + "; ".join(tried) + "). Set TFNSW_API_KEY in .env "
        f"(free at opendata.transport.nsw.gov.au), or save the zip from {GTFS_PAGE} into raw/manual/gtfs/")


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
        raise MissingCredential(f"no stops.txt found in {snap.files['main']['path']}")
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
    raise MissingCredential(f"{path.name}: no sheet with 'Latitude' and 'Longitude' columns")


def _lights_resource(ctx) -> tuple:
    """(url, catalogue modified date) of the spreadsheet listed in the Data.NSW catalogue."""
    r = ctx.get(LIGHTS_CKAN, params={"id": LIGHTS_DATASET})
    r.raise_for_status()
    result = r.json()["result"]
    url = next(x["url"] for x in result["resources"] if x["url"].lower().split("?")[0].endswith((".xlsx", ".csv")))
    return url, (result.get("metadata_modified") or "")[:10]


def _release_from_name(name: str, fallback: str) -> str:
    m = re.search(rf"({_MONTHS})[-_ ]?(\d{{4}})", name, re.I)
    return f"{m.group(1).capitalize()} {m.group(2)}" if m else fallback


def fetch_lights(ctx) -> Snapshot:
    problem = ""
    try:
        url, modified = _lights_resource(ctx)
        name = url.rsplit("/", 1)[-1]
        rec = ctx.download("traffic_lights", "main", url, filename=name)
        return Snapshot("traffic_lights", _release_from_name(name, f"catalogue updated {modified}"), url,
                        {"main": rec}, {"catalogue_modified": modified})
    except (EtlError, requests.RequestException, ValueError, KeyError, StopIteration) as e:
        problem = str(e)
    src = _newest(MANUAL / "traffic_lights", ("*.xlsx", "*.xlsm", "*.csv"))
    if src is None:
        raise MissingCredential(
            f"traffic_lights could not be downloaded ({problem}). Save the spreadsheet from {LIGHTS_PAGE} "
            "into raw/manual/traffic_lights/")
    ctx.log("  traffic_lights: download failed, using the file in raw/manual/traffic_lights/")
    rec = ctx.adopt("traffic_lights", "main", src)
    return Snapshot("traffic_lights", _release_from_name(src.name, "manual file"), LIGHTS_PAGE, {"main": rec})


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
           "Transport for NSW", ("stops",), fetch_stops, parse_stops, check_stops),
    Source("traffic_lights", "TfNSW Traffic Lights Location", "CC BY (Data.NSW)", "Transport for NSW",
           ("traffic_lights",), fetch_lights, parse_lights, check_lights),
]
