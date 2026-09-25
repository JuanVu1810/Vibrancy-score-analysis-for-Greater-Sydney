"""Pandera schemas: the contract for each table the ETL produces.

Follows the CPI forecast project's platform_validation module: pandera is used lazily (all failures are
collected, not just the first), values are coerced before checking, and if pandera isn't installed the
check returns a WARNING record instead of stopping the ETL. Pandera is pinned in requirements.lock, so
in Docker it is always there.

A schema says which columns a table has, their types, whether they may be empty, which values are
allowed and which ranges are plausible. It complements the built-in checks in each source module, which
cover what a schema can't (row counts, joins to the SA2 boundaries, thresholds). Schemas are strict
(unexpected columns fail) where the parser decides the columns, and loose where the publisher's
extra columns are kept (traffic lights).
"""
from __future__ import annotations

import importlib.util
from functools import lru_cache

from .core import AU_BBOX, NSW_BBOX
from .quality import QualityRecord, counts

SA2_CODE_RANGE = (100_000_000, 199_999_999)  # NSW SA2 codes start with 1
SA1_CODE_RANGE = (10_000_000_000, 19_999_999_999)  # NSW SA1 and mesh block codes have 11 digits and start with 1
ROAD_TYPES = ("residential", "living_street", "unclassified", "tertiary", "tertiary_link", "secondary",
              "secondary_link", "primary", "primary_link", "trunk", "trunk_link", "pedestrian")
INDUSTRIES = list("ABCDEFGHIJKLMNOPQRS")
AGE_BANDS = ["0-4", "5-9", "10-14", "15-19", "20-24", "25-29", "30-34", "35-39", "40-44", "45-49",
             "50-54", "55-59", "60-64", "65-69", "70-74", "75-79", "80-84", "85-and-over"]
BUSINESS_COUNTS = ["0_to_50k_businesses", "50k_to_200k_businesses", "200k_to_2m_businesses",
                   "2m_to_5m_businesses", "5m_to_10m_businesses", "10m_or_more_businesses", "total_businesses"]


def pandera_available() -> bool:
    return importlib.util.find_spec("pandera") is not None


@lru_cache(maxsize=1)
def build_schemas() -> dict:
    """Table name -> pandera schema. Built once, and only when pandera is available."""
    import pandera.geopandas as pag
    import pandera.pandas as pa

    def ints(names, lo=None, hi=None, nullable=True, unique=False):
        checks = [pa.Check.in_range(lo, hi)] if lo is not None and hi is not None else \
                 [pa.Check.ge(0)] if lo == 0 else []
        return {n: pa.Column("Int64", checks=checks, nullable=nullable, unique=unique) for n in names}

    def text(names, nullable=False, allowed=None, unique=False):
        checks = [pa.Check.isin(allowed)] if allowed else []
        return {n: pa.Column(str, checks=checks, nullable=nullable, unique=unique) for n in names}

    def points(box, nullable=False):
        def inside(s):
            p = s.dropna()
            return p.x.between(box[0], box[2]) & p.y.between(box[1], box[3])
        return pa.Column("geometry", checks=[pa.Check(inside, name=f"inside {box}", element_wise=False)],
                         nullable=nullable)

    def polygons():
        return pa.Column("geometry", checks=[pa.Check(lambda s: ~s.dropna().is_empty, name="not empty",
                                                      element_wise=False)], nullable=False)

    def lines():
        return pa.Column("geometry", checks=[
            pa.Check(lambda s: (s.dropna().geom_type == "LineString") & ~s.dropna().is_empty, name="a line",
                     element_wise=False)], nullable=False)

    def table(columns, geo=False, strict=True, unique=None):
        schema = pag.DataFrameSchema if geo else pa.DataFrameSchema
        return schema(columns, coerce=True, strict=strict, unique=unique)

    return {
        "sa2_boundaries": table({
            **ints(["SA2_CODE21"], *SA2_CODE_RANGE, nullable=False, unique=True),
            **ints(["SA3_CODE21", "SA4_CODE21", "STE_CODE21"], nullable=False),
            **ints(["CHG_FLAG21"]),
            **text(["SA2_NAME21", "SA3_NAME21", "SA4_NAME21", "STE_NAME21"]),
            **text(["GCC_NAME21"], allowed=["Greater Sydney"]),
            **text(["GCC_CODE21", "AUS_CODE21", "AUS_NAME21", "CHG_LBL21", "LOCI_URI21"], nullable=True),
            "AREASQKM21": pa.Column(float, pa.Check.gt(0), nullable=False),
            "geom": polygons()}, geo=True),
        "mesh_blocks": table({
            **ints(["MB_CODE21"], *SA1_CODE_RANGE, nullable=False, unique=True),
            **text(["category"]),
            "area_sqkm": pa.Column(float, pa.Check.ge(0), nullable=True),
            **ints(["dwellings", "persons"], lo=0),
            **ints(["SA1_CODE21"], *SA1_CODE_RANGE, nullable=False),
            **ints(["SA2_CODE21"], *SA2_CODE_RANGE, nullable=False)}),
        "businesses": table({
            **text(["industry_code"], allowed=INDUSTRIES),
            **text(["industry_name", "sa2_name"]),
            **ints(["SA2_CODE21"], *SA2_CODE_RANGE, nullable=False),
            **ints(BUSINESS_COUNTS, lo=0)}, unique=["industry_code", "SA2_CODE21"]),
        "income": table({
            **ints(["SA2_CODE21"], *SA2_CODE_RANGE, nullable=False, unique=True),
            **text(["sa2_name"]),
            **ints(["earners"], lo=0),
            **ints(["median_age"], 10, 90),
            **ints(["median_income", "mean_income"], 5_000, 400_000)}),
        "population": table({
            **ints(["SA2_CODE21"], *SA2_CODE_RANGE, nullable=False, unique=True),
            **text(["sa2_name"]),
            **ints([f"{a}_people" for a in AGE_BANDS] + ["total_people"], lo=0, nullable=False)}),
        "schools": table({
            **ints(["USE_ID"], nullable=False),
            **text(["CATCH_TYPE"]),
            **text(["USE_DESC"], nullable=True),
            "geom": polygons()}, geo=True, strict=False),
        "hospitals": table({
            **ints(["topoid"], nullable=False, unique=True),
            **text(["generalname"]),
            **text(["alternativelabel"], nullable=True),
            **ints(["classsubtype", "operationalstatus"]),
            "geom": points(AU_BBOX)}, geo=True),
        "polling_places": table({
            **text(["state"], allowed=["NSW"]),
            **ints(["division_id"], nullable=False),
            **ints(["polling_place_id"], nullable=False, unique=True),
            **ints(["polling_place_type_id"], 1, 10, nullable=False),
            **ints(["premises_post_code"], 1000, 9999),
            **text(["division_name", "polling_place_name"]),
            **text(["premises_name", "premises_address_1", "premises_address_2", "premises_address_3",
                    "premises_suburb"], nullable=True),
            "geom": points(NSW_BBOX, nullable=True)}, geo=True),
        "stops": table({
            **text(["stop_id"], unique=True),
            **text(["stop_name"], nullable=True),
            **text(["stop_code", "parent_station", "platform_code"], nullable=True),
            "location_type": pa.Column("Int64", pa.Check.isin([0, 1, 2, 3, 4]), nullable=False),  # GTFS values
            "wheelchair_boarding": pa.Column("Int64", pa.Check.isin([0, 1, 2]), nullable=True),
            "geom": points(AU_BBOX, nullable=True)}, geo=True),
        "traffic_lights": table({
            **text(["asset_type"], allowed=["Vehicle", "Pedestrian", "Re-active Maintenance"]),
            "equipment_id": pa.Column(nullable=False, unique=True),
            "geom": points(NSW_BBOX, nullable=True)}, geo=True, strict=False),
        "public_amenities": table({
            **text(["osm_id"], unique=True),
            **text(["amenity"], allowed=["toilets", "drinking_water"]),
            **text(["name"], nullable=True),
            "geom": points(NSW_BBOX)}, geo=True),
        "roads": table({
            **text(["osm_id"], unique=True),
            **text(["highway"], allowed=list(ROAD_TYPES)),
            **text(["name"], nullable=True),
            "geom": lines()}, geo=True),
        "daily_living_shops": table({
            **text(["osm_id"], unique=True),
            **text(["kind"], allowed=["supermarket", "convenience"]),
            **text(["shop", "amenity", "name", "brand"], nullable=True),
            **text(["mapped_as"], allowed=["node", "area"]),
            "geom": points(NSW_BBOX)}, geo=True),
        "crossings": table({
            **text(["osm_id"], unique=True),
            **text(["crossing", "crossing_ref", "crossing_markings"], nullable=True),
            "is_zebra": pa.Column(bool, nullable=False),
            "geom": points(NSW_BBOX)}, geo=True),
    }


def _describe(failures) -> str:
    """The first few failure cases of a pandera error, in one line."""
    shown = []
    for _, row in failures.head(3).iterrows():
        column = row["column"] if row["column"] is not None and str(row["column"]) != "nan" else "table"
        shown.append(f"{column}: {row['check']} (e.g. {str(row['failure_case'])[:40]})")
    more = f" and {len(failures) - 3} more" if len(failures) > 3 else ""
    return f"schema failed with {len(failures)} failure case(s): " + "; ".join(shown) + more


def validate_table(name: str, frame) -> QualityRecord:
    """Check one table against its schema and return a record named "pandera:<table>"."""
    rows, cols, missing, dupes = counts(name, frame)

    def record(status: str, notes: str) -> QualityRecord:
        return QualityRecord(f"pandera:{name}", status, rows, cols, missing, dupes, notes)

    if not pandera_available():
        return record("WARNING", "Pandera is not installed; only the built-in checks were used.")
    import pandera.pandas as pa

    schema = build_schemas().get(name)
    if schema is None:
        return record("WARNING", "no schema is defined for this table")
    try:
        schema.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as exc:
        return record("FAIL", _describe(exc.failure_cases))
    except Exception as exc:  # a schema that can't run is a problem too, not a pass
        return record("FAIL", f"schema could not be applied: {type(exc).__name__}: {str(exc)[:120]}")
    return record("PASS", "schema validation passed")
