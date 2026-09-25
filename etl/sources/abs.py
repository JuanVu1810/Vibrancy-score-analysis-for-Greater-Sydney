"""Australian Bureau of Statistics sources: SA2 boundaries, businesses, income and population.

The three statistical tables are Excel workbooks with a few title rows above the data, and their
layout differs slightly between releases. The parsers therefore find their header rows by content
and take the newest year in the workbook, so a new release is picked up without code changes.
The same parsers read older releases, which is how `verify --parity` checks them against data/.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

import geopandas as gpd
import pandas as pd
from openpyxl import load_workbook
from shapely.geometry import MultiPolygon

from ..core import (EtlError, Snapshot, Source, error, is_sa2_code, to_int, warn)
from ..stage import greater_sydney_codes

ABS = "https://www.abs.gov.au"
LICENCE = "CC BY 4.0"
ATTRIBUTION = "Australian Bureau of Statistics"

GS_SA2_COUNT = 373  # SA2s in Greater Sydney, ASGS Edition 3 (2021)


def find_link(html: str, pattern: str) -> str | None:
    """First href on a page whose URL contains the regex `pattern`, as an absolute URL."""
    m = re.search(r'href="([^"]*' + pattern + r'[^"]*)"', html)
    return urljoin(ABS, m.group(1)) if m else None


def _null_int(series) -> pd.Series:
    return pd.array([to_int(v) for v in series], dtype="Int64")


# =============================================================================================
# SA2 boundaries
# =============================================================================================
SA2_ZIP = (f"{ABS}/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/"
           "jul2021-jun2026/access-and-downloads/digital-boundary-files/SA2_2021_AUST_SHP_GDA2020.zip")
_SA2_INT = ["SA2_CODE21", "CHG_FLAG21", "SA3_CODE21", "SA4_CODE21", "STE_CODE21"]
_SA2_COLS = ["SA2_CODE21", "SA2_NAME21", "CHG_FLAG21", "CHG_LBL21", "SA3_CODE21", "SA3_NAME21",
             "SA4_CODE21", "SA4_NAME21", "GCC_CODE21", "GCC_NAME21", "STE_CODE21", "STE_NAME21",
             "AUS_CODE21", "AUS_NAME21", "AREASQKM21", "LOCI_URI21"]


def to_multipolygon(geom):
    return MultiPolygon([geom]) if geom is not None and geom.geom_type == "Polygon" else geom


def fetch_sa2(ctx) -> Snapshot:
    rec = ctx.download("asgs_sa2", "main", SA2_ZIP, filename="SA2_2021_AUST_SHP_GDA2020.zip")
    return Snapshot("asgs_sa2", "ASGS Edition 3 (2021)", SA2_ZIP, {"main": rec})


def parse_sa2(snap: Snapshot) -> dict:
    gdf = gpd.read_file(f"zip://{snap.path()}")
    gdf = gdf[gdf["GCC_NAME21"] == "Greater Sydney"].copy()
    gdf = gdf.to_crs(epsg=4326)
    for col in _SA2_INT:
        gdf[col] = _null_int(gdf[col])
    gdf["geometry"] = gdf["geometry"].apply(to_multipolygon)
    gdf = gdf[_SA2_COLS + ["geometry"]].sort_values("SA2_CODE21").reset_index(drop=True)
    return {"sa2_boundaries": gdf.rename_geometry("geom")}


def check_sa2(out: dict, ctx) -> list:
    gdf, issues = out["sa2_boundaries"], []
    if len(gdf) != GS_SA2_COUNT:
        issues.append(error(f"expected {GS_SA2_COUNT} Greater Sydney SA2s, got {len(gdf)}"))
    if gdf["SA2_CODE21"].duplicated().any():
        issues.append(error("duplicate SA2 codes"))
    if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
        issues.append(error("empty or missing geometry"))
    minx, miny, maxx, maxy = gdf.total_bounds
    if not (149.5 < minx and maxx < 152.0 and -34.5 < miny and maxy < -32.5):
        issues.append(error(f"boundaries fall outside the Sydney area: {gdf.total_bounds}"))
    if not gdf.geometry.is_valid.all():
        issues.append(warn(f"{int((~gdf.geometry.is_valid).sum())} invalid geometries"))
    return issues


# =============================================================================================
# Businesses (Counts of Australian Businesses, cube 9: industry x SA2 x turnover size)
# =============================================================================================
CABEE = f"{ABS}/statistics/economy/business-indicators/counts-australian-businesses-including-entries-and-exits"
BUSINESS_COLS = ["industry_code", "industry_name", "SA2_CODE21", "sa2_name", "0_to_50k_businesses",
                 "50k_to_200k_businesses", "200k_to_2m_businesses", "2m_to_5m_businesses",
                 "5m_to_10m_businesses", "10m_or_more_businesses", "total_businesses"]
INDUSTRIES = set("ABCDEFGHIJKLMNOPQRS")  # ANZSIC divisions; 'X' (currently unknown) is dropped


def fetch_business(ctx) -> Snapshot:
    """Newest release that has the SA2 turnover cube. The SA2 cubes of the newest release come
    out months after its headline numbers, so walk back through the earlier releases."""
    year = datetime.now().year
    slugs = ["latest-release"] + [f"jul{y - 4}-jun{y}" for y in range(year + 1, 2021, -1)]
    for slug in slugs:
        page = f"{CABEE}/{slug}"
        r = ctx.get(page)
        if r.status_code != 200:
            continue
        link = find_link(r.text, r"8165DC09(?:_revised)?\.xlsx")
        if link:
            rec = ctx.download("abs_business", "main", link)
            return Snapshot("abs_business", "unknown", link, {"main": rec}, {"release_page": page})
    raise EtlError("abs_business: no release page offers the SA2 by turnover cube (data cube 9)")


def business_sheet(wb):
    """(worksheet, year) of the newest June in a CABEE cube; each sheet holds one June."""
    best = None
    for ws in wb.worksheets:
        # The sheet's own title line ("... Turnover Size Ranges, June 2025"); other lines mention other Junes.
        titles = [str(r[0]) for r in ws.iter_rows(min_row=1, max_row=6, max_col=1, values_only=True)
                  if r[0] and "Turnover" in str(r[0])]
        years = re.findall(r"June (\d{4})", titles[0]) if titles else []
        if years and (best is None or int(years[-1]) > best[1]):
            best = (ws, int(years[-1]))
    if best is None:
        raise EtlError("no 'Businesses by ... Turnover Size Ranges, June YYYY' sheet found")
    return best


_BUSINESS_HEADER = ["zero to less than $50k", "$50k to less than $200k", "$200k to less than $2m",
                    "$2m to less than $5m", "$5m to less than $10m", "$10m or more", "total"]


def check_business_header(ws) -> None:
    """The parser reads the count columns by position, so make sure they are the turnover bands we expect.
    The June 2021 cube, for example, used different bands, and would otherwise be read into the wrong columns."""
    for r in ws.iter_rows(min_row=1, max_row=15, max_col=11, values_only=True):
        if r[0] == "Industry" and r[2] == "SA2":
            found = [str(c).strip().lower() for c in r[4:11]]
            if found != [h.lower() for h in _BUSINESS_HEADER]:
                raise EtlError(f"business sheet {ws.title!r}: turnover columns are {list(r[4:11])}, "
                               f"expected {_BUSINESS_HEADER}; the layout changed, so the parser needs updating")
            return
    raise EtlError(f"business sheet {ws.title!r}: no header row (Industry, SA2 ...) found")


def parse_business_ws(ws) -> tuple:
    """(NSW businesses DataFrame with industries A to S, number of rows dropped for industry X)."""
    check_business_header(ws)
    rows, dropped_x = [], 0
    for r in ws.iter_rows(min_col=1, max_col=11, values_only=True):
        code = str(r[0]).strip() if r[0] is not None else ""
        if len(code) != 1 or not code.isalpha() or not is_sa2_code(r[2]):
            continue
        sa2 = str(r[2]).strip()
        if not sa2.startswith("1"):  # NSW SA2 codes start with 1
            continue
        if code not in INDUSTRIES:
            dropped_x += 1
            continue
        rows.append([code, r[1], int(sa2), r[3]] + [to_int(v) for v in r[4:11]])
    df = pd.DataFrame(rows, columns=BUSINESS_COLS)
    for col in BUSINESS_COLS[4:]:
        df[col] = df[col].astype("Int64")
    return df.sort_values(["SA2_CODE21", "industry_code"]).reset_index(drop=True), dropped_x


def parse_business(snap: Snapshot) -> dict:
    wb = load_workbook(snap.path(), read_only=True, data_only=True)
    ws, year = business_sheet(wb)
    df, dropped_x = parse_business_ws(ws)
    snap.release = f"June {year}"
    snap.extra.update(sheet=ws.title, dropped_industry_x_rows=dropped_x)
    return {"businesses": df}


def check_business(out: dict, ctx) -> list:
    df, issues = out["businesses"], []
    if set(df["industry_code"]) != INDUSTRIES:
        issues.append(error(f"industries differ from A to S: {sorted(set(df['industry_code']))}"))
    if df["SA2_CODE21"].nunique() < 600:
        issues.append(error(f"only {df['SA2_CODE21'].nunique()} NSW SA2s"))
    if df.duplicated(["industry_code", "SA2_CODE21"]).any():
        issues.append(error("duplicate industry and SA2 rows"))
    if df[BUSINESS_COLS[4:]].isna().any().any():
        issues.append(warn(f"{int(df[BUSINESS_COLS[4:]].isna().sum().sum())} empty count cells"))
    gs = greater_sydney_codes(ctx)
    if gs is not None and gs - set(df["SA2_CODE21"]):
        issues.append(error(f"{len(gs - set(df['SA2_CODE21']))} Greater Sydney SA2s are missing"))
    return issues


# =============================================================================================
# Income (Personal Income in Australia, Table 1: total income, SA2 sheet)
# =============================================================================================
INCOME_PAGE = f"{ABS}/statistics/labour/earnings-and-working-conditions/personal-income-australia/latest-release"
INCOME_COLS = ["SA2_CODE21", "sa2_name", "earners", "median_age", "median_income", "mean_income"]
# ABS group headings above the yearly columns -> our column names
_INCOME_GROUPS = (("Earners", "earners"), ("Median age", "median_age"),
                  ("Median (", "median_income"), ("Mean (", "mean_income"))


def fetch_income(ctx) -> Snapshot:
    r = ctx.get(INCOME_PAGE)
    r.raise_for_status()
    link = find_link(r.text, r"Table%201%20-%20Total%20income")
    if not link:
        raise EtlError("abs_income: 'Table 1 - Total income' not found on the latest release page")
    rec = ctx.download("abs_income", "main", link, filename="personal_income_table1.xlsx")
    m = re.search(r"personal-income-australia/([\d-]+)/", link)
    return Snapshot("abs_income", m.group(1) if m else "unknown", link, {"main": rec},
                    {"release_page": INCOME_PAGE})


def parse_income_ws(ws, year: str | None = None) -> tuple:
    """(NSW income DataFrame, year label) from the 'Table 1.4' SA2 sheet. `year` like '2020-21'
    picks that column; the default is the newest."""
    rows = list(ws.iter_rows(min_col=1, max_col=40, values_only=True))
    h = next((i for i, r in enumerate(rows) if r[0] == "SA2"), None)
    if h is None:
        raise EtlError("income sheet: no header row starting with 'SA2'")
    groups, years = rows[h - 1], rows[h]
    starts = [c for c, g in enumerate(groups) if isinstance(g, str) and g.strip()]
    cols, chosen = {}, year
    for label, name in _INCOME_GROUPS:
        start = next((c for c in starts if groups[c].strip().startswith(label)), None)
        if start is None:
            raise EtlError(f"income sheet: no '{label}' column group")
        end = next((c for c in starts if c > start), len(groups))
        span = [c for c in range(start, end) if isinstance(years[c], str)]
        chosen = chosen or max(years[c] for c in span)
        cols[name] = next(c for c in span if years[c] == chosen)
    data = []
    for r in rows[h + 1:]:
        if is_sa2_code(r[0]) and str(r[0]).strip().startswith("1"):
            data.append([int(str(r[0]).strip()), r[1]] + [to_int(r[cols[n]]) for _, n in _INCOME_GROUPS])
    df = pd.DataFrame(data, columns=INCOME_COLS)
    for col in INCOME_COLS[2:]:
        df[col] = df[col].astype("Int64")
    return df.sort_values("SA2_CODE21").reset_index(drop=True), chosen


def parse_income(snap: Snapshot) -> dict:
    wb = load_workbook(snap.path(), read_only=True, data_only=True)
    df, year = parse_income_ws(wb["Table 1.4"])
    snap.release = year
    return {"income": df}


def check_income(out: dict, ctx) -> list:
    df, issues = out["income"], []
    if len(df) < 600:
        issues.append(error(f"only {len(df)} NSW SA2s"))
    if df["SA2_CODE21"].duplicated().any():
        issues.append(error("duplicate SA2 codes"))
    mi = df["median_income"].dropna()
    if len(mi) and not (5_000 < mi.min() and mi.max() < 400_000):
        issues.append(error(f"median income outside 5k to 400k: {mi.min()} to {mi.max()}"))
    if df[INCOME_COLS[2:]].isna().any().any():
        issues.append(warn(f"{int(df[INCOME_COLS[2:]].isna().any(axis=1).sum())} SA2s have a missing value (np)"))
    gs = greater_sydney_codes(ctx)
    if gs is not None and gs - set(df["SA2_CODE21"]):
        issues.append(error(f"{len(gs - set(df['SA2_CODE21']))} Greater Sydney SA2s are missing"))
    return issues


# =============================================================================================
# Population (Regional population by age and sex, SA2, persons)
# =============================================================================================
POP_PAGE = f"{ABS}/statistics/people/population/regional-population-age-and-sex/latest-release"
AGE_COLS = ["0-4", "5-9", "10-14", "15-19", "20-24", "25-29", "30-34", "35-39", "40-44", "45-49",
            "50-54", "55-59", "60-64", "65-69", "70-74", "75-79", "80-84", "85-and-over"]
POP_COLS = ["SA2_CODE21", "sa2_name"] + [f"{a}_people" for a in AGE_COLS] + ["total_people"]


def fetch_population(ctx) -> Snapshot:
    r = ctx.get(POP_PAGE)
    r.raise_for_status()
    link = find_link(r.text, r"32350DS0001_\d{4}\.xlsx")
    if not link:
        raise EtlError("abs_population: the SA2 by age workbook (32350DS0001) was not found")
    year = re.search(r"32350DS0001_(\d{4})", link).group(1)
    rec = ctx.download("abs_population", "main", link)
    return Snapshot("abs_population", f"30 June {year}", link, {"main": rec}, {"release_page": POP_PAGE})


def _age_label(label) -> str | None:
    s = str(label).strip().replace("–", "-").replace("—", "-").lower()
    if s.startswith("total"):
        return "total"
    s = s.replace(" and over", "-and-over").replace(" ", "-")
    return s if s in AGE_COLS else None


def population_sheet(wb):
    """The persons table: the sheet whose title mentions persons (males and females are separate)."""
    for ws in wb.worksheets:
        head = " ".join(str(c) for r in ws.iter_rows(min_row=1, max_row=3, max_col=1, values_only=True)
                        for c in r if c).lower()
        if "persons" in head and "age" in head:
            return ws
    return wb["Table 3"]


def parse_population_ws(ws, year: int | None = None) -> pd.DataFrame:
    """Greater Sydney SA2 populations by five-year age band. Workbooks with one row per SA2 and year
    (the 2001 to latest series) need `year`."""
    rows = list(ws.iter_rows(min_col=1, max_col=40, values_only=True))
    h = next((i for i, r in enumerate(rows) if "SA2 code" in r), None)
    if h is None:
        raise EtlError("population sheet: no 'SA2 code' header")
    head, ages = rows[h], rows[h - 1]
    c_code, c_name, c_gcc = head.index("SA2 code"), head.index("SA2 name"), head.index("GCCSA code")
    c_year = head.index("Year") if "Year" in head else None
    bands = {}
    for c in range(c_name + 1, len(ages)):
        key = _age_label(ages[c]) if ages[c] is not None else None
        if key:
            bands[key] = c
    missing = [a for a in AGE_COLS + ["total"] if a not in bands]
    if missing:
        raise EtlError(f"population sheet: age columns not found: {missing}")
    data = []
    for r in rows[h + 1:]:
        if r[c_gcc] != "1GSYD" or not is_sa2_code(r[c_code]):
            continue
        if c_year is not None and year is not None and to_int(r[c_year]) != year:
            continue
        data.append([int(str(r[c_code]).strip()), r[c_name]] + [to_int(r[bands[a]]) for a in AGE_COLS + ["total"]])
    df = pd.DataFrame(data, columns=POP_COLS)
    for col in POP_COLS[2:]:
        df[col] = df[col].astype("Int64")
    return df.sort_values("SA2_CODE21").reset_index(drop=True)


def parse_population(snap: Snapshot) -> dict:
    wb = load_workbook(snap.path(), read_only=True, data_only=True)
    return {"population": parse_population_ws(population_sheet(wb))}


def check_population(out: dict, ctx) -> list:
    df, issues = out["population"], []
    if len(df) != GS_SA2_COUNT:
        issues.append(error(f"expected {GS_SA2_COUNT} Greater Sydney SA2s, got {len(df)}"))
    if df["SA2_CODE21"].duplicated().any():
        issues.append(error("duplicate SA2 codes"))
    if df[POP_COLS[2:]].isna().any().any():
        issues.append(error("empty population cells"))
    band_sum = df[[f"{a}_people" for a in AGE_COLS]].sum(axis=1)
    off = (band_sum - df["total_people"]).abs()
    if (off > 5).any():
        issues.append(warn(f"{int((off > 5).sum())} SA2s where the age bands don't add up to the total"))
    total = int(df["total_people"].sum())
    if not (4_500_000 < total < 7_000_000):
        issues.append(error(f"Greater Sydney total of {total:,} people looks wrong"))
    gs = greater_sydney_codes(ctx)
    if gs is not None and gs != set(df["SA2_CODE21"]):
        issues.append(error("population SA2s differ from the boundary SA2s"))
    return issues


SOURCES = [
    Source("asgs_sa2", "SA2 boundaries (ASGS Edition 3, 2021)", LICENCE, ATTRIBUTION,
           ("sa2_boundaries",), fetch_sa2, parse_sa2, check_sa2),
    Source("abs_business", "Counts of Australian Businesses (SA2 by industry by turnover)", LICENCE,
           ATTRIBUTION, ("businesses",), fetch_business, parse_business, check_business),
    Source("abs_income", "Personal Income in Australia (SA2, total income)", LICENCE, ATTRIBUTION,
           ("income",), fetch_income, parse_income, check_income),
    Source("abs_population", "Regional population by age and sex (SA2, persons)", LICENCE, ATTRIBUTION,
           ("population",), fetch_population, parse_population, check_population),
]
