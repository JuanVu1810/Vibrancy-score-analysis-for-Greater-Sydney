"""OpenStreetMap: public toilets, drinking water and pedestrian crossings from one Geofabrik snapshot.

One dated extract of the whole state is reproducible (the manifest records its checksum) and feeds four tables:
public toilets and drinking water, pedestrian crossings (mapped points only), and, for an AUO-style walkability measure,
the walkable road network and the shops of the daily living index. OSM data is (c) OpenStreetMap contributors, ODbL.

Roads follow the Australian Urban Observatory's "walkable road network that excluded highways and
freeways": residential, unclassified, living streets, tertiary, secondary, primary, trunk and pedestrian
streets. Footways and paths (mostly sidewalks that run beside a road, which would double count it), service
roads, tracks and motorways are left out. Ways marked foot=no, or private and not open to foot traffic, are dropped.

Shops follow the AUO daily living index (Higgs et al. 2019): a supermarket is shop=supermarket or a
convenience or grocery shop named after Aldi, Coles, Foodworks, IGA or Woolworths; a convenience store is
shop=convenience, a newsagent or a petrol station. Shops mapped as buildings count too, at their centre.

Zebra crossings: mappers have moved from crossing=zebra to crossing=uncontrolled (or marked) plus
crossing:markings=zebra, so about 700 nodes still use the old tag while about 8,000 carry the new one.
`is_zebra` covers both.
"""
from __future__ import annotations

import re

import geopandas as gpd
import pandas as pd

from ..core import NSW_BBOX, SYDNEY_BBOX, Snapshot, Source, error, inside, warn

AMENITIES = ("toilets", "drinking_water")
# The OSM driver puts 'highway' in a column and everything else in an hstore-style 'other_tags' string.
WHERE = ("highway = 'crossing' OR other_tags LIKE '%\"amenity\"=>\"toilets\"%' "
         "OR other_tags LIKE '%\"amenity\"=>\"drinking_water\"%'")
_HSTORE = re.compile(r'"((?:[^"\\]|\\.)*)"=>"((?:[^"\\]|\\.)*)"')

TYPICAL_AMENITIES, TYPICAL_ZEBRA = 6595, 1825  # counts from an earlier extract (May 2024), a sanity check on the size

ROAD_TYPES = ("residential", "living_street", "unclassified", "tertiary", "tertiary_link", "secondary",
              "secondary_link", "primary", "primary_link", "trunk", "trunk_link", "pedestrian")
CHAINS = re.compile(r"\b(aldi|coles|foodworks|iga|woolworths)\b", re.I)
SHOP_NODES_WHERE = ("other_tags LIKE '%\"shop\"=>\"supermarket\"%' OR other_tags LIKE '%\"shop\"=>\"convenience\"%' "
                    "OR other_tags LIKE '%\"shop\"=>\"newsagent\"%' OR other_tags LIKE '%\"shop\"=>\"grocery\"%' "
                    "OR other_tags LIKE '%\"amenity\"=>\"fuel\"%'")
SHOP_AREAS_WHERE = "shop IN ('supermarket','convenience','newsagent','grocery') OR amenity = 'fuel'"


def _tags(s) -> dict:
    return dict(_HSTORE.findall(s)) if isinstance(s, str) else {}


def walkable(tags: dict) -> bool:
    """Can people walk along this road? Not marked foot=no, not a motorroad, and not private unless foot is allowed."""
    if tags.get("foot") == "no" or tags.get("motorroad") == "yes":
        return False
    if tags.get("access") in ("no", "private") and tags.get("foot") not in ("yes", "designated", "permissive"):
        return False
    return True


def classify_shop(shop, amenity, text: str):
    """"supermarket", "convenience" or None, following the AUO daily living index."""
    if shop == "supermarket":
        return "supermarket"
    if shop in ("convenience", "grocery") and CHAINS.search(text or ""):
        return "supermarket"  # for example a small IGA that is mapped as a convenience shop
    if shop in ("convenience", "newsagent") or amenity == "fuel":
        return "convenience"
    return None


def _roads(path):
    import pyogrio

    where = "highway IN (" + ", ".join(f"'{h}'" for h in ROAD_TYPES) + ")"
    lines = pyogrio.read_dataframe(path, layer="lines", bbox=SYDNEY_BBOX, where=where)
    keep = lines["other_tags"].map(_tags).map(walkable)
    lines = lines[keep]
    return gpd.GeoDataFrame({"osm_id": lines["osm_id"].astype(str), "highway": lines["highway"], "name": lines["name"]},
                            geometry=lines.geometry, crs=4326).reset_index(drop=True)


def _shops(path):
    import pyogrio

    nodes = pyogrio.read_dataframe(path, layer="points", bbox=SYDNEY_BBOX, where=SHOP_NODES_WHERE)
    areas = pyogrio.read_dataframe(path, layer="multipolygons", bbox=SYDNEY_BBOX, where=SHOP_AREAS_WHERE)
    parts = []
    for frame, mapped_as in ((nodes, "node"), (areas, "area")):
        tags = frame["other_tags"].map(_tags)
        shop = tags.map(lambda t: t.get("shop")) if mapped_as == "node" else frame["shop"]
        amenity = tags.map(lambda t: t.get("amenity")) if mapped_as == "node" else frame["amenity"]
        brand = tags.map(lambda t: t.get("brand"))
        text = frame["name"].fillna("") + " " + brand.fillna("")
        kind = pd.Series([classify_shop(s, a, x) for s, a, x in zip(shop, amenity, text)], index=frame.index)
        if mapped_as == "node":
            ids = "n" + frame["osm_id"].astype(str)
            geom = frame.geometry
        else:  # a building or a multipolygon: use its centre, worked out in metres (GDA2020 / MGA zone 56)
            ids = pd.Series(["w" + str(w) if pd.notna(w) else "r" + str(r)
                             for w, r in zip(frame["osm_way_id"], frame["osm_id"])], index=frame.index)
            geom = frame.geometry.to_crs(7856).centroid.to_crs(4326)
        part = gpd.GeoDataFrame({"osm_id": ids, "kind": kind, "shop": shop, "amenity": amenity, "name": frame["name"],
                                 "brand": brand, "mapped_as": mapped_as}, geometry=geom, crs=4326)
        parts.append(part[part["kind"].notna()])
    return pd.concat(parts, ignore_index=True)


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
    roads = _roads(str(snap.path()))
    shops = _shops(str(snap.path()))
    snap.extra.update(roads=len(roads), roads_by_type=roads["highway"].value_counts().to_dict(),
                      supermarkets=int((shops["kind"] == "supermarket").sum()),
                      convenience_stores=int((shops["kind"] == "convenience").sum()),
                      shops_mapped_as_areas=int((shops["mapped_as"] == "area").sum()))
    return {"public_amenities": amenities.rename_geometry("geom"), "crossings": crossings.rename_geometry("geom"),
            "roads": roads.rename_geometry("geom"), "daily_living_shops": gpd.GeoDataFrame(
                shops, geometry="geometry", crs=4326).rename_geometry("geom")}


def check(out: dict, ctx) -> list:
    am, cr, issues = out["public_amenities"], out["crossings"], []
    for kind in AMENITIES:
        if not (am["amenity"] == kind).any():
            issues.append(error(f"no '{kind}' points found"))
    if len(am) and not (TYPICAL_AMENITIES / 2 <= len(am) <= TYPICAL_AMENITIES * 2):
        issues.append(warn(f"{len(am):,} amenities, against about {TYPICAL_AMENITIES:,} in an earlier extract (May 2024)"))
    if not len(cr):
        issues.append(error("no crossings found"))
    elif int(cr["is_zebra"].sum()) < TYPICAL_ZEBRA / 2:  # more than before is expected, see the module notes
        issues.append(warn(f"only {int(cr['is_zebra'].sum()):,} zebra crossings, against about {TYPICAL_ZEBRA:,} in an earlier extract"))
    for name, gdf in (("amenities", am), ("crossings", cr), ("roads", out["roads"]),
                      ("shops", out["daily_living_shops"])):
        if not inside(gdf.total_bounds, NSW_BBOX):
            issues.append(error(f"{name} fall outside NSW: {gdf.total_bounds}"))
    roads, shops = out["roads"], out["daily_living_shops"]
    if len(roads) < 50_000:
        issues.append(error(f"only {len(roads):,} road segments in Greater Sydney, expected well over 100,000"))
    for kind, least in (("supermarket", 300), ("convenience", 500)):
        n = int((shops["kind"] == kind).sum())
        if n < least:
            issues.append(error(f"only {n} {kind} shops, expected at least {least}"))
    return issues


SOURCES = [
    Source("osm_nsw", "OpenStreetMap, New South Wales (Geofabrik extract)", "ODbL 1.0 (share-alike)",
           "(c) OpenStreetMap contributors", ("public_amenities", "crossings", "roads", "daily_living_shops"), parse, check),
]
