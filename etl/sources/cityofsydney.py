"""City of Sydney open data: trees, stairs and mobility parking (CC BY 4.0).

They cover the City of Sydney area only (about 5 x 8 km of the inner city), so they are extras for that area, not Greater
Sydney layers. The ETL does not download them: `download_data.py` does, and these sources take its files from
raw/manifest.json. Columns keep the publisher's names, lower-cased.
"""
from __future__ import annotations

import geopandas as gpd

from ..core import NSW_BBOX, Snapshot, Source, error, inside

# source id (and table name) -> title, and the fewest rows a healthy layer has (Sep 2026: 49,640 / 523 / 365)
LAYERS = {"cos_trees": ("City of Sydney trees", 40_000),
          "cos_stairs": ("City of Sydney stairs", 400),
          "cos_mobility_parking": ("City of Sydney mobility parking", 300)}


def parse(snap: Snapshot) -> dict:
    gdf = gpd.read_file(snap.path())
    gdf.columns = [c if c == gdf.geometry.name else c.lower() for c in gdf.columns]
    snap.release = f"live service, retrieved {snap.retrieved_at[:10]}"
    return {snap.source_id: gdf.rename_geometry("geom")}


def check(out: dict, ctx) -> list:
    issues = []
    for name, gdf in out.items():
        if len(gdf) < LAYERS[name][1]:
            issues.append(error(f"{name}: only {len(gdf)} rows"))
        if gdf["objectid"].duplicated().any():
            issues.append(error(f"{name}: duplicate objectid values"))
        if gdf.geometry.isna().any() or not inside(gdf.total_bounds, NSW_BBOX):
            issues.append(error(f"{name}: missing or out-of-area locations {gdf.total_bounds}"))
    return issues


SOURCES = [Source(name, title, "CC BY 4.0", "City of Sydney", (name,), parse, check)
           for name, (title, _) in LAYERS.items()]
