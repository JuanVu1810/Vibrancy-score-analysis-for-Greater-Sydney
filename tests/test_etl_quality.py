"""Tests for the ETL's quality records and pandera schemas. They use small made-up tables, no network.

Run inside the Docker image:
    docker compose run --rm --no-deps --entrypoint python etl -m pytest tests -q
"""
import geopandas as gpd
import pandas as pd
import pytest
from openpyxl import Workbook

pytest.importorskip("pandera")

from etl import quality, schemas  # noqa: E402
from etl.core import EtlError, Source, error, to_int, warn  # noqa: E402
from etl.sources import abs as abs_sources  # noqa: E402


def ints(values):
    return pd.array(values, dtype="Int64")


def businesses(**overrides):
    frame = pd.DataFrame({
        "industry_code": ["A", "G"], "industry_name": ["Agriculture, Forestry and Fishing", "Retail Trade"],
        "SA2_CODE21": ints([101021007, 101021007]), "sa2_name": ["Braidwood", "Braidwood"],
        **{c: ints([5, 9]) for c in schemas.BUSINESS_COUNTS}})
    for column, value in overrides.items():
        frame[column] = value
    return frame


def points(lons, lats):
    return gpd.points_from_xy(lons, lats)


def traffic_lights(asset_types=("Vehicle", "Pedestrian"), lons=(151.2, 151.3), lats=(-33.8, -33.9), **extra):
    frame = pd.DataFrame({"asset_type": list(asset_types), "equipment_id": [1, 2], "suburb": ["SYDNEY", "GLEBE"],
                          **extra})
    return gpd.GeoDataFrame(frame, geometry=points(lons, lats), crs=4326).rename_geometry("geom")


# --- quality records -----------------------------------------------------------------------------
def test_record_status_follows_the_worst_issue():
    frames = {"businesses": businesses()}
    assert quality.record_from_issues("abs_business", frames, []).status == "PASS"
    assert quality.record_from_issues("abs_business", frames, [warn("5 SA2s have a missing value")]).status == "WARNING"
    record = quality.record_from_issues("abs_business", frames, [warn("minor"), error("only 3 SA2s")])
    assert record.status == "FAIL"
    assert "only 3 SA2s" in record.notes


def test_record_counts_rows_and_duplicate_keys():
    twice = pd.concat([businesses(), businesses()], ignore_index=True)
    record = quality.record_from_issues("abs_business", {"businesses": twice}, [])
    assert record.rows == 4
    assert record.duplicate_keys == 2


def test_assess_gives_one_built_in_record_and_one_pandera_record_per_table():
    source = Source("abs_business", "t", "l", "a", ("businesses",), None, None, lambda out, ctx: [warn("check")])
    records = quality.assess(source, {"businesses": businesses()}, ctx=None)
    assert [r.dataset for r in records] == ["abs_business", "pandera:businesses"]
    assert [r.status for r in records] == ["WARNING", "PASS"]


# --- pandera schemas: what they catch ------------------------------------------------------------
def test_valid_tables_pass():
    assert schemas.validate_table("businesses", businesses()).status == "PASS"
    assert schemas.validate_table("traffic_lights", traffic_lights()).status == "PASS"


def test_a_new_industry_code_fails():
    record = schemas.validate_table("businesses", businesses(industry_code=["A", "T"]))
    assert record.status == "FAIL"
    assert "industry_code" in record.notes


def test_a_negative_count_fails():
    record = schemas.validate_table("businesses", businesses(total_businesses=ints([5, -3])))
    assert record.status == "FAIL"
    assert "total_businesses" in record.notes


def test_a_renamed_or_extra_column_fails_when_the_schema_is_strict():
    renamed = businesses().rename(columns={"total_businesses": "total"})
    assert schemas.validate_table("businesses", renamed).status == "FAIL"


def test_an_unexpected_asset_type_fails():
    # VEH became Vehicle in the June 2026 release; a further change should be noticed
    record = schemas.validate_table("traffic_lights", traffic_lights(asset_types=("Vehicle", "Signal")))
    assert record.status == "FAIL"
    assert "asset_type" in record.notes


def test_publisher_columns_are_kept_when_the_schema_is_loose():
    assert schemas.validate_table("traffic_lights", traffic_lights(street_3=[None, "X ST"])).status == "PASS"


def test_a_point_outside_the_expected_area_fails_but_an_empty_geometry_is_allowed():
    far = schemas.validate_table("traffic_lights", traffic_lights(lons=(151.2, -30.5), lats=(-33.8, 30.5)))
    assert far.status == "FAIL"
    empty = traffic_lights()
    empty.loc[1, "geom"] = None  # the ETL blanks typo coordinates instead of guessing
    assert schemas.validate_table("traffic_lights", empty).status == "PASS"


def test_suppressed_income_cells_are_allowed_but_implausible_values_are_not():
    income = pd.DataFrame({"SA2_CODE21": ints([101021007, 101021008]), "sa2_name": ["Braidwood", "Karabar"],
                           "earners": ints([2467, None]), "median_age": ints([51, None]),
                           "median_income": ints([46640, None]), "mean_income": ints([68904, None])})
    assert schemas.validate_table("income", income).status == "PASS"
    income.loc[0, "median_income"] = 4_600_000  # a value in cents, say
    assert schemas.validate_table("income", income).status == "FAIL"


def test_without_pandera_the_check_warns_instead_of_stopping(monkeypatch):
    monkeypatch.setattr(schemas, "pandera_available", lambda: False)
    record = schemas.validate_table("businesses", businesses())
    assert record.status == "WARNING"
    assert "not installed" in record.notes


def test_a_gtfs_location_type_outside_the_specification_fails():
    stops = gpd.GeoDataFrame(
        {"stop_id": ["a", "b"], "stop_name": ["One", "Two"], "stop_code": [None, None], "parent_station": [None, "a"],
         "platform_code": [None, None], "location_type": ints([0, 1]), "wheelchair_boarding": ints([0, None])},
        geometry=points([151.2, 151.3], [-33.8, -33.9]), crs=4326).rename_geometry("geom")
    assert schemas.validate_table("stops", stops).status == "PASS"
    stops["location_type"] = ints([0, 9])
    record = schemas.validate_table("stops", stops)
    assert record.status == "FAIL"
    assert "location_type" in record.notes


# --- business sheet layout -----------------------------------------------------------------------
def business_sheet(bands):
    wb = Workbook()
    ws = wb.active
    ws.append(["title"])
    ws.append(["Industry", "Industry", "SA2", "SA2"] + bands)
    ws.append(["Code", "Label", "Code", "Label"] + ["no."] * len(bands))
    ws.append(["A", "Agriculture, Forestry and Fishing", "101021007", "Braidwood", 1, 2, 3, 4, 0, 0, 10])
    ws.append(["X", "Currently Unknown", "101021007", "Braidwood", 1, 0, 0, 0, 0, 0, 1])
    ws.append(["A", "Agriculture, Forestry and Fishing", "801011001", "Acton", 1, 0, 0, 0, 0, 0, 1])  # ACT, not NSW
    return ws


CURRENT_BANDS = ["Zero to less than $50k", "$50k to less than $200k", "$200k to less than $2m",
                 "$2m to less than $5m", "$5m to less than $10m", "$10m or more", "Total"]


def test_business_parser_keeps_nsw_industries_a_to_s_and_counts_dropped_x():
    frame, dropped_x = abs_sources.parse_business_ws(business_sheet(CURRENT_BANDS))
    assert len(frame) == 1
    assert frame.loc[0, "SA2_CODE21"] == 101021007
    assert frame.loc[0, "total_businesses"] == 10
    assert dropped_x == 1


def test_business_parser_refuses_a_layout_with_different_turnover_bands():
    june_2021 = ["Zero to less than $50k", "$50k to less than $100k", "$100k to less than $200K",
                 "$200k to less than $500k", "$500k to less than $2m", "$2m to less than $5m", "$5m to less than $10m"]
    with pytest.raises(EtlError, match="layout changed"):
        abs_sources.parse_business_ws(business_sheet(june_2021))


# --- small helpers -------------------------------------------------------------------------------
@pytest.mark.parametrize("value, expected", [("2,467", 2467), (2467.0, 2467), ("np", None), ("", None),
                                              (None, None), ("12.6", 13), ("n/a", None)])
def test_to_int_reads_abs_cells(value, expected):
    assert to_int(value) == expected
