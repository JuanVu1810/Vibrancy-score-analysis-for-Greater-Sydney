"""OpenStreetMap: public toilets, drinking water and pedestrian crossings from one Geofabrik snapshot.

v1 used Overpass turbo exports taken on different days. One dated extract of the whole state is
reproducible (the manifest records its checksum) and can later feed the road network and shop layers.
Like v1, only mapped points (OSM nodes) are used. OSM data is (c) OpenStreetMap contributors, ODbL.

Zebra crossings: v1 counted nodes tagged crossing=zebra (1,825 in May 2024). Mappers have since moved
to crossing=uncontrolled (or marked) plus crossing:markings=zebra, so only about 700 nodes still use the
old tag while about 8,000 carry the new one. `is_zebra` covers both, so expect a much higher count than v1.
"""
from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

import geopandas as gpd
import pandas as pd

from ..core import NSW_BBOX, Snapshot, Source, error, inside, warn

GEOFABRIK = "https://download.geofabrik.de/australia-oceania/australia/new-south-wales-latest.osm.pbf"
AMENITIES = ("toilets", "drinking_water")
# The OSM driver puts 'highway' in a column and everything else in an hstore-style 'other_tags' string.
WHERE = ("highway = 'crossing' OR other_tags LIKE '%\"amenity\"=>\"toilets\"%' "
         "OR other_tags LIKE '%\"amenity\"=>\"drinking_water\"%'")
_HSTORE = re.compile(r'"((?:[^"\\]|\\.)*)"=>"((?:[^"\\]|\\.)*)"')

V1_AMENITIES, V1_CROSSINGS = 6595, 1825  # the v1 Overpass exports (May 2024), for a sanity comparison


def _tags(s) -> dict:
    return dict(_HSTORE.findall(s)) if isinstance(s, str) else {}


def fetch(ctx) -> Snapshot:
    rec = ctx.download("osm_nsw", "main", GEOFABRIK, filename="new-south-wales-latest.osm.pbf")
    when = rec.get("last_modified")
    release = f"Geofabrik extract of {parsedate_to_datetime(when).date()}" if when else "Geofabrik extract"
    return Snapshot("osm_nsw", release, GEOFABRIK, {"main": rec})


def parse(snap: Snapshot) -> dict:
    import pyogrio  # imported here so listing and checking sources doesn't need the OSM reader

    pts = pyogrio.read_dataframe(str(snap.path()), layer="points", where=WHERE)
    tags = pts["other_tags"].map(_tags)
    amenity = tags.map(lambda t: t.get("amenity"))

    am = pts[amenity.isin(AMENITIES)]
    amenities = gpd.GeoDataFrame(
        {"osm_id": am["osm_id"].astype(str), "amenity": amenity[am.index], "name": am["name"]},
        geometry=am.geometry, crs=4326).reset_index(drop=True)

    cr = pts[pts["highway"] == "crossing"]
    ct = tags[cr.index]
    crossing = ct.map(lambda t: t.get("crossing"))
    ref = ct.map(lambda t: t.get("crossing_ref"))
    marks = ct.map(lambda t: t.get("crossing:markings"))
    crossings = gpd.GeoDataFrame(
        {"osm_id": cr["osm_id"].astype(str), "crossing": crossing, "crossing_ref": ref,
         "crossing_markings": marks,
         "is_zebra": (crossing == "zebra") | (ref == "zebra") | (marks == "zebra")},
        geometry=cr.geometry, crs=4326).reset_index(drop=True)

    snap.extra.update(toilets=int((amenities["amenity"] == "toilets").sum()),
                      drinking_water=int((amenities["amenity"] == "drinking_water").sum()),
                      crossings=len(crossings), zebra_crossings=int(crossings["is_zebra"].sum()),
                      crossing_tag_zebra_only=int((crossings["crossing"] == "zebra").sum()))
    return {"public_amenities": amenities.rename_geometry("geom"), "crossings": crossings.rename_geometry("geom")}


def check(out: dict, ctx) -> list:
    am, cr, issues = out["public_amenities"], out["crossings"], []
    for kind in AMENITIES:
        if not (am["amenity"] == kind).any():
            issues.append(error(f"no '{kind}' points found"))
    if len(am) and not (V1_AMENITIES / 2 <= len(am) <= V1_AMENITIES * 2):
        issues.append(warn(f"{len(am):,} amenities, against {V1_AMENITIES:,} in v1 (Overpass, May 2024)"))
    if not len(cr):
        issues.append(error("no crossings found"))
    elif int(cr["is_zebra"].sum()) < V1_CROSSINGS / 2:  # more than v1 is expected, see the module notes
        issues.append(warn(f"only {int(cr['is_zebra'].sum()):,} zebra crossings, against {V1_CROSSINGS:,} in v1"))
    for name, gdf in (("amenities", am), ("crossings", cr)):
        if not inside(gdf.total_bounds, NSW_BBOX):
            issues.append(error(f"{name} fall outside NSW: {gdf.total_bounds}"))
    return issues


SOURCES = [
    Source("osm_nsw", "OpenStreetMap, New South Wales (Geofabrik extract)", "ODbL 1.0 (share-alike)",
           "(c) OpenStreetMap contributors", ("public_amenities", "crossings"), fetch, parse, check),
]
