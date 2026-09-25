"""NSW Government sources: school catchments (Department of Education) and hospitals (Spatial Services)."""
from __future__ import annotations

import json
import zipfile

import geopandas as gpd
import pandas as pd
import requests

from ..core import NSW_BBOX, EtlError, Snapshot, Source, error, inside, warn
from .abs import to_multipolygon

# =============================================================================================
# School catchments
# =============================================================================================
CKAN = "https://data.nsw.gov.au/data/api/3/action/package_show"
CATCH_DATASET = "nsw-education-school-intake-zones-catchment-areas-for-nsw-government-schools"
CATCH_FALLBACK = ("https://data.nsw.gov.au/data/dataset/8b1e8161-7252-43d9-81ed-6311569cb1d7/resource/"
                  "32d6f502-ddb1-45d9-b114-5e34ddfd33ac/download/catchments.zip")
_KEEP = ["USE_ID", "CATCH_TYPE", "USE_DESC"]


def fetch_catchments(ctx) -> Snapshot:
    """Resolve the zip through the Data.NSW catalogue, falling back to the last known URL."""
    url, modified = CATCH_FALLBACK, None
    try:
        r = ctx.get(CKAN, params={"id": CATCH_DATASET})
        result = r.json()["result"]
        url = next(x["url"] for x in result["resources"] if x["url"].lower().endswith(".zip"))
        modified = result.get("metadata_modified")
    except (requests.RequestException, ValueError, KeyError, StopIteration):
        ctx.log("  school catchments: catalogue lookup failed, using the last known URL")
    rec = ctx.download("catchments", "main", url, filename="catchments.zip")
    return Snapshot("catchments", "unknown", url, {"main": rec}, {"catalogue_modified": modified})


def _read_zipped(path, member: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(f"/vsizip/{path}/{member}")
    gdf = gdf.to_crs(epsg=4326)
    missing = [c for c in _KEEP if c not in gdf.columns]
    if missing:
        raise EtlError(f"{member}: columns {missing} not found (has {list(gdf.columns)})")
    return gdf[_KEEP + ["geometry"]]


def parse_catchments(snap: Snapshot) -> dict:
    """Primary and secondary catchments stacked. Where a school also has a future catchment, its
    future catchment(s) replace the current one, as in the v1 notebook. A school with two future
    polygons keeps both, and future catchments for schools with no current one are left out."""
    path = snap.path()
    primary = _read_zipped(path, "catchments_primary.shp")
    secondary = _read_zipped(path, "catchments_secondary.shp")
    future = _read_zipped(path, "catchments_future.shp")
    with zipfile.ZipFile(path) as z:
        info = json.loads(z.read("catchment_sf_info.json"))

    present = pd.concat([primary, secondary], ignore_index=True)
    replaced = present["USE_ID"].isin(future["USE_ID"])
    used = future[future["USE_ID"].isin(present["USE_ID"])].copy()
    current = present.drop_duplicates("USE_ID").set_index("USE_ID")
    for col in ("CATCH_TYPE", "USE_DESC"):  # an empty future value keeps the current one
        used[col] = used[col].where(used[col].notna(), used["USE_ID"].map(current[col]))
    combined = pd.concat([present[~replaced], used], ignore_index=True)
    combined["USE_ID"] = combined["USE_ID"].astype("Int64")
    combined["geometry"] = combined["geometry"].apply(to_multipolygon)
    out = gpd.GeoDataFrame(combined, geometry="geometry", crs=4326)

    snap.release = f"enrolment year {info.get('current_enrolment_year', 'unknown')}"
    snap.extra.update(primary=len(primary), secondary=len(secondary), future=len(future),
                      schools_with_future_catchment=int(present.loc[replaced, "USE_ID"].nunique()),
                      future_rows_used=len(used), future_rows_dropped=len(future) - len(used),
                      enrolment_year=info.get("current_enrolment_year"))
    return {"schools": out.rename_geometry("geom")}


def check_catchments(out: dict, ctx) -> list:
    gdf, issues = out["schools"], []
    if len(gdf) < 1500:
        issues.append(error(f"only {len(gdf)} catchments"))
    if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
        issues.append(error("empty or missing catchment geometry"))
    if gdf["USE_ID"].isna().any():
        issues.append(error("catchments without a school id"))
    if not gdf.geometry.is_valid.all():
        issues.append(warn(f"{int((~gdf.geometry.is_valid).sum())} invalid catchment polygons"))
    return issues


# =============================================================================================
# Hospitals (NSW Features of Interest, Health Facilities, layer 1)
# =============================================================================================
HOSPITAL_LAYER = ("https://portal.spatial.nsw.gov.au/server/rest/services/NSW_FOI_Health_Facilities/"
                  "MapServer/1")
_PAGE = 1000


def fetch_hospitals(ctx) -> Snapshot:
    """Page through the ArcGIS layer as GeoJSON (WGS84)."""
    features, offset = [], 0
    while True:
        r = ctx.get(f"{HOSPITAL_LAYER}/query", params={
            "where": "1=1", "outFields": "topoid,generalname,alternativelabel,classsubtype,operationalstatus",
            "returnGeometry": "true", "outSR": 4326, "f": "geojson", "orderByFields": "objectid",
            "resultOffset": offset, "resultRecordCount": _PAGE})
        r.raise_for_status()
        page = r.json()
        if "error" in page:
            raise EtlError(f"hospitals: the service returned an error: {page['error']}")
        features += page["features"]
        if not (page.get("exceededTransferLimit") or page.get("properties", {}).get("exceededTransferLimit")):
            break
        offset += _PAGE
    data = json.dumps({"type": "FeatureCollection", "features": features}).encode("utf-8")
    rec = ctx.store("hospitals", "main", "hospitals.geojson", data, f"{HOSPITAL_LAYER}/query")
    return Snapshot("hospitals", f"live service, retrieved {ctx.today}", HOSPITAL_LAYER, {"main": rec})


def parse_hospitals(snap: Snapshot) -> dict:
    gdf = gpd.read_file(snap.path())
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    for col in ("topoid", "classsubtype", "operationalstatus"):
        gdf[col] = pd.to_numeric(gdf[col], errors="coerce").astype("Int64")
    gdf = gdf[["topoid", "generalname", "alternativelabel", "classsubtype", "operationalstatus", "geometry"]]
    return {"hospitals": gdf.reset_index(drop=True).rename_geometry("geom")}


def check_hospitals(out: dict, ctx) -> list:
    gdf, issues = out["hospitals"], []
    if len(gdf) < 250:
        issues.append(error(f"only {len(gdf)} hospitals"))
    if not inside(gdf.total_bounds, NSW_BBOX):
        issues.append(error(f"hospitals fall outside NSW: {gdf.total_bounds}"))
    if gdf["topoid"].duplicated().any():
        issues.append(warn("duplicate hospital ids"))
    return issues


SOURCES = [
    Source("catchments", "NSW school intake zones (catchment areas)", "CC BY (Data.NSW)",
           "NSW Department of Education", ("schools",), fetch_catchments, parse_catchments, check_catchments),
    Source("hospitals", "NSW Features of Interest: Health Facilities (hospitals)",
           "not verified (NSW Spatial Services)", "NSW Spatial Services", ("hospitals",),
           fetch_hospitals, parse_hospitals, check_hospitals),
]
