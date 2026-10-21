#!/usr/bin/env python3
"""Build the Greater Sydney vibrancy story from saved output tables."""

import argparse
import html
import json
import math
import random
import textwrap
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
TEMPLATE = Path(__file__).with_name("vibrancy_story_template.html")
# The colour-roles table: the one place in the code where every named colour is defined, for both themes. Every
# other colour name in this file (RAMP, PLACE_COLORS, ...) and every colour in the template's CSS
# is a copy of a value from here, so a colour only ever needs to change in one place.
PILLAR_ORDER = ["Intensity", "Diversity", "Design"]
PILLAR_CSS_NAME = {"Intensity": "intensity", "Diversity": "diversity", "Design": "design"}
COLOR_ROLES = {
    "light": {
        "ink": "#0b0b0b", "not-scored": "#343434", "chosen-ring": "#ffffff",
        "chart-text-dark": "#000000", "chart-text-light": "#ffffff",
        "fifth-1": "#86b6ef", "fifth-2": "#5598e7", "fifth-3": "#2a78d6", "fifth-4": "#1c5cab", "fifth-5": "#0d366b",
        "cluster-high-high": "#D6402E", "cluster-low-low": "#6A2C9B", "cluster-high-low": "#F2A898",
        "cluster-low-high": "#C4A6E6", "cluster-not-significant": "#E4E3DD",
        "unavailable": "#d7d7d3", "muted": "#898781",
        "intensity-1": "#EEDCBC", "intensity-2": "#E2C28A", "intensity-3": "#D6A858", "intensity-4": "#CC912D",
        "intensity-5": "#C27A00", "intensity-text": "#C27A00", "intensity-bar": "#C27A00",
        "diversity-1": "#97C2BB", "diversity-2": "#71ACA2", "diversity-3": "#4C968A", "diversity-4": "#268172",
        "diversity-5": "#006B5A", "diversity-text": "#006B5A", "diversity-bar": "#006B5A",
        "design-1": "#D0BDC8", "design-2": "#AD8B9E", "design-3": "#8A5875", "design-4": "#6C2D52",
        "design-5": "#4D002D", "design-text": "#4D002D", "design-bar": "#4D002D",
        "place-dense-diverse": "#006B5A", "place-less-dense-diverse": "#71ACA2",
        "place-dense-less-diverse": "#A47F6B", "place-less-dense-less-diverse": "#E3D5C7",
        # A place colour used as text (map legends, the "kinds of place" scatter corners) needs its
        # own darker shade: the map-fill colours above are only tested to read against a white or
        # coloured fill, not to read as small text on the page's own surface. Each shade below is the
        # same hue and saturation as its fill colour, just darkened until it clears 4.5:1 contrast on
        # --surface (the same bar the pillar "-text" roles above are held to); where the fill colour
        # already clears 4.5:1 on its own (dense and diverse), the text role reuses it unchanged.
        # "less dense and less diverse" is darkened further still, past the 4.5:1 floor: its fill starts
        # so pale (1.4:1) that stopping at the floor left it too close to "dense and less diverse", whose
        # fill barely needed darkening at all; the extra darkening keeps the two readably distinct.
        "place-dense-diverse-text": "#006B5A", "place-less-dense-diverse-text": "#477a71",
        "place-dense-less-diverse-text": "#8f6b58", "place-less-dense-less-diverse-text": "#644b32",
        # One colour for each dataset on the page's data map (the last section of the page).
        "data-stops": "#0072B2", "data-intersections": "#2b2b2b", "data-crossings": "#D55E00",
        "data-shops": "#E69F00", "data-amenities": "#009E73", "data-traffic_lights": "#CC3366",
        "data-polling_places": "#7B3FA0", "data-hospitals": "#C8102E",
        "data-schools_primary": "#8C6D1F", "data-schools_high": "#4F5D75", "data-schools_infants": "#6E8B1A",
    },
    "dark": {
        "ink": "#ffffff", "not-scored": "#f0efe9", "chosen-ring": "#ffffff",
        "chart-text-dark": "#000000", "chart-text-light": "#ffffff",
        "fifth-1": "#49627e", "fifth-2": "#5c7fa8", "fifth-3": "#76a4e1", "fifth-4": "#9ac5f4", "fifth-5": "#c6e2ff",
        "cluster-high-high": "#E8583F", "cluster-low-low": "#BC86F0", "cluster-high-low": "#FFB9AC",
        "cluster-low-high": "#E0CDFA", "cluster-not-significant": "#3B3B38",
        "unavailable": "#d7d7d3", "muted": "#aaa8a0",
        "intensity-1": "#8C7D52", "intensity-2": "#A3915D", "intensity-3": "#BAA568", "intensity-4": "#DDC279",
        "intensity-5": "#FFE08A", "intensity-text": "#FFE08A", "intensity-bar": "#FFE08A",
        "diversity-1": "#105C4F", "diversity-2": "#0C7563", "diversity-3": "#088E78", "diversity-4": "#04A78C",
        "diversity-5": "#00C0A0", "diversity-text": "#00C0A0", "diversity-bar": "#00C0A0",
        "design-1": "#321E27", "design-2": "#5A243E", "design-3": "#7A2A51", "design-4": "#9A2F63",
        "design-5": "#BA3476", "design-text": "#BA3476", "design-bar": "#BA3476",
        "place-dense-diverse": "#00C0A0", "place-less-dense-diverse": "#0C7563",
        "place-dense-less-diverse": "#AB8876", "place-less-dense-less-diverse": "#3F3224",
        # Same lighten-until-4.5:1 rule as the light theme above, but lightened rather than darkened,
        # since dark theme text needs to stand out against the near-black surface instead; "less dense
        # and less diverse" is lightened further still for the same distinctness reason as light theme.
        "place-dense-diverse-text": "#00C0A0", "place-less-dense-diverse-text": "#109a82",
        "place-dense-less-diverse-text": "#AB8876", "place-less-dense-less-diverse-text": "#c6b29c",
        # Lighter shades of the same hues, so the dots stand out on the dark map.
        "data-stops": "#56B4E9", "data-intersections": "#ededed", "data-crossings": "#FF8A50",
        "data-shops": "#F5C242", "data-amenities": "#2FD3A0", "data-traffic_lights": "#FF6F9C",
        "data-polling_places": "#C39BE6", "data-hospitals": "#FF5A5F",
        "data-schools_primary": "#D9B76A", "data-schools_high": "#9FB1D1", "data-schools_infants": "#B7D56A",
    },
}
# Light-theme colours read from the table above, for the static figures and the page's map data.
RAMP = [COLOR_ROLES["light"][f"fifth-{step}"] for step in range(1, 6)]
HOTSPOT_COLOR = COLOR_ROLES["light"]["not-scored"]
# The datasets on the page's data map, in the order of the buttons. The key names the colour (data-<key> in
# COLOR_ROLES) and the file map_layers/<key>.js. A "points" dataset is drawn as dots, with a radius in pixels at the
# default zoom, and its hover total is density times area from the "count_column" of the scores file. An "areas"
# dataset is drawn as outlines, and its hover total comes from the school group table. The points run from the most
# numerous dataset to the fewest, and the page draws later ones on top of earlier ones.
DATA_MAP_LAYERS = [
    {"key": "intersections", "name": "Street intersections", "kind": "points", "radius": 0.9, "count_column": "intersections_per_km2"},
    {"key": "crossings", "name": "Pedestrian crossings", "kind": "points", "radius": 1.3, "count_column": "crossings_per_km2"},
    {"key": "stops", "name": "Transport stops", "kind": "points", "radius": 1.3, "count_column": "stops_per_km2"},
    {"key": "shops", "name": "Everyday shops", "kind": "points", "radius": 1.8, "count_column": "shops_per_km2"},
    {"key": "amenities", "name": "Public toilets and drinking water", "kind": "points", "radius": 1.5, "count_column": "amenities_per_km2"},
    {"key": "traffic_lights", "name": "Traffic lights", "kind": "points", "radius": 1.6, "count_column": "traffic_lights_per_km2"},
    {"key": "polling_places", "name": "Polling places", "kind": "points", "radius": 2.2, "count_column": "polling_places_per_km2"},
    {"key": "hospitals", "name": "Hospitals", "kind": "points", "radius": 3.5, "count_column": "hospitals_per_km2"},
    {"key": "schools_primary", "name": "Primary school catchments", "kind": "areas", "group": "primary"},
    {"key": "schools_high", "name": "High school catchments", "kind": "areas", "group": "high"},
    {"key": "schools_infants", "name": "Infants school catchments", "kind": "areas", "group": "infants"},
]
MAP_POINT_KEYS = [layer["key"] for layer in DATA_MAP_LAYERS if layer["kind"] == "points"]
SCHOOL_GROUPS = [layer["group"] for layer in DATA_MAP_LAYERS if layer["kind"] == "areas"]
MAP_EDGE_MARGIN = 0.15
MAP_COORDINATE_DIGITS = 5
SCHOOL_SIMPLIFY_TOLERANCE = 0.0003
SCHOOL_GRID_SIZE = 0.0001
PLACE_CSS_NAME = {
    "dense and diverse": "dense-diverse",
    "dense and less diverse": "dense-less-diverse",
    "less dense and diverse": "less-dense-diverse",
    "less dense and less diverse": "less-dense-less-diverse",
}
PLACE_COLORS = {label: COLOR_ROLES["light"][f"place-{name}"] for label, name in PLACE_CSS_NAME.items()}
HOTSPOT_STYLES = {
    "high-high": {"weight": 1.5, "dash": ""},
    "low-low": {"weight": 1.5, "dash": "5 3"},
    "high-low": {"weight": 1.2, "dash": "2 2"},
    "low-high": {"weight": 1.2, "dash": "7 2 2 2"},
}
# The static chart figures. The score axes run from 70 to 130 on the page, so they do too here.
GUIDE_COLOR = "#c3c2b7"
DOT_SIZE = 16
DOT_SEED = 20261017
TITLE_WIDTH = 90
SCORE_AXIS_LOW = 70
SCORE_AXIS_HIGH = 130
MORAN_AXIS_LOW = 60
HISTOGRAM_BIN = 2
DISTANCE_BANDS = [
    (0, 5, "Within 5 km"), (5, 10, "5 to 10 km"), (10, 20, "10 to 20 km"), (20, 40, "20 to 40 km"),
    (40, np.inf, "Over 40 km"),
]
# Where a dot's name may sit beside it, tried in order: right and above, left and above, right and below, left and below.
LABEL_OFFSETS = [(6, 6, "left", "bottom"), (-6, 6, "right", "bottom"), (6, -6, "left", "top"), (-6, -6, "right", "top")]
# The squares picture in the Limitations section: how many squares per row, the pixels from one square to the next,
# and the size of a square. The chance picture uses the usual 0.05 cut-off for a "significant" local Moran's I test.
GRID_COLUMNS = 31
GRID_STEP = 14
GRID_SQUARE = 11
CHANCE_LEVEL = 0.05
CHANCE_SEED = 20261001
# A card fact whose density is below these limits is shown as a whole-number total instead ("6 street intersections in
# total"), because a small density such as 0.05 per km² is hard to picture. The page's profile card uses the same limits.
SMALL_RESIDENTS_PER_HA = 1
SMALL_DENSITY_PER_KM2 = 1
# The four card facts: label, density column, unit after a density (one, many), the noun after a total (one, many),
# and the limit. A displayed 1 takes the singular unit; every other number takes the plural.
CARD_FACTS = [
    ("Residents per hectare", "residents_per_ha", ("resident per hectare", "residents per hectare"),
     ("resident", "residents"), SMALL_RESIDENTS_PER_HA),
    ("Registered businesses", "businesses_per_km2", ("business per km²", "businesses per km²"),
     ("registered business", "registered businesses"), SMALL_DENSITY_PER_KM2),
    ("Stops", "stops_per_km2", ("stop per km²", "stops per km²"), ("stop", "stops"), SMALL_DENSITY_PER_KM2),
    ("Street intersections", "intersections_per_km2", ("intersection per km²", "intersections per km²"),
     ("street intersection", "street intersections"), SMALL_DENSITY_PER_KM2),
]
# Local Moran's I clusters: the class order, plain names for the page, and each class's colour role in COLOR_ROLES.
# No cluster colour is one of the fifths' blues or a place-type colour.
HOTSPOT_ORDER = ["high-high", "low-low", "high-low", "low-high", "not significant"]
HOTSPOT_NAMES = {
    "high-high": "High-high: high score, high-scoring neighbours",
    "low-low": "Low-low: low score, low-scoring neighbours",
    "high-low": "High-low: high score, lower-scoring neighbours",
    "low-high": "Low-high: low score, higher-scoring neighbours",
    "not significant": "Not a cluster",
}
HOTSPOT_CSS_NAME = {
    "high-high": "cluster-high-high", "low-low": "cluster-low-low", "high-low": "cluster-high-low",
    "low-high": "cluster-low-high", "not significant": "cluster-not-significant",
}
# Static maps: thin, semi-transparent outlines so they do not dominate the picture (the page draws them thicker,
# because there they can be switched off). The key names each outline class in plain words.
STATIC_OUTLINE_WIDTH = 0.7
STATIC_OUTLINE_ALPHA = 0.7
OUTLINE_KEY_HEADER = "Outline: nearby SA2s with similar scores"
OUTLINE_KEY_LABELS = {
    "high-high": "High-high hot spot",
    "low-low": "Low-low cold spot",
    "high-low": "High-low outlier: high among low neighbours",
    "low-high": "Low-high outlier: low among high neighbours",
}
UNAVAILABLE_COLOR = COLOR_ROLES["light"]["unavailable"]
MUTED_COLOR = COLOR_ROLES["light"]["muted"]
NOT_SCORED_OUTLINE = COLOR_ROLES["light"]["not-scored"]
RANK_QUINTILES = [
    ("Top quintile", 1, 75),
    ("Second quintile", 76, 149),
    ("Middle quintile", 150, 224),
    ("Fourth quintile", 225, 298),
    ("Bottom quintile", 299, 372),
]
# The stability chart's thin "swings to" bar is this fraction lighter than its median bar's own quintile
# colour (0 none, 1 white); the page's own tint() function uses the same fraction.
RANK_RANGE_TINT_AMOUNT = 0.5
# The distance chart's labelled outer exceptions: farther than this from the CBD, the top few by score.
DISTANCE_OUTER_KM = 10
DISTANCE_OUTER_COUNT = 3
CARD_NAMES = [
    "Darlinghurst", "Sydney (South) - Haymarket", "Gosford - Springfield", "Wetherill Park Industrial",
]
CBD_LON = 151.2073
CBD_LAT = -33.8678
METRIC_CRS = 7856
# Fixed story frame: a readable metropolitan view is a design choice, not a data claim.
START_VIEW = [[-34.10, 150.65], [-33.60, 151.35]]
# The short methods summary that opens the final panel.
METHODS_DETAIL = (
    "The score combines 14 indicators in three pillars. Intensity is how much is packed into an area "
    "(ten indicators), Diversity is how varied its mix of businesses and land uses is (two), and Design "
    "is how connected its streets are (two). Each indicator is put on a common scale and averaged, and "
    "the three pillars count equally. 22 alternative versions test how much the ranking depends on "
    "these choices."
)



def css_color_variables(theme):
    """Return the CSS variables for one theme from the colour-roles table."""
    roles = COLOR_ROLES[theme]
    variables = [
        f"--ink:{roles['ink']}",
        f"--muted:{roles['muted']}",
        f"--chosen-ring:{roles['chosen-ring']}",
        f"--unavailable:{roles['unavailable']}",
        f"--chart-text-dark:{roles['chart-text-dark']}",
        f"--chart-text-light:{roles['chart-text-light']}",
    ]
    variables.extend(f"--c{index}:{roles[f'fifth-{index + 1}']}" for index in range(5))
    for label in PILLAR_ORDER:
        name = PILLAR_CSS_NAME[label]
        variables.extend(f"--{name}-{index}:{roles[f'{name}-{index + 1}']}" for index in range(5))
        variables.append(f"--{name}-text:{roles[f'{name}-text']}")
        variables.append(f"--{name}-bar:{roles[f'{name}-bar']}")
    # Each place colour has a darker (or, in the dark theme, lighter) "-text" shade for a place-type name written
    # as coloured letters; see the COLOR_ROLES comment above.
    for name in PLACE_CSS_NAME.values():
        variables.append(f"--place-{name}:{roles[f'place-{name}']}")
        variables.append(f"--place-{name}-text:{roles[f'place-{name}-text']}")
    for name in HOTSPOT_CSS_NAME.values():
        variables.append(f"--{name}:{roles[name]}")
    for layer in DATA_MAP_LAYERS:
        variables.append(f"--data-{layer['key']}:{roles['data-' + layer['key']]}")
    return ";\n    ".join(variables) + ";"


def place_css_class(place_type):
    """Return the CSS class suffix for one place type."""
    return PLACE_CSS_NAME.get(place_type, "not-scored")


def pillar_html(text):
    """Wrap the three pillar names in their theme-aware text-colour spans."""
    for label in PILLAR_ORDER:
        name = PILLAR_CSS_NAME[label]
        span = f'<span class="pillar-text {name}-text">{label}</span>'
        text = text.replace(label, span)
    return text


def rank_class(rank, number_of_sa2s):
    """Return a top-to-bottom rank-fifth class index for one rank."""
    if pd.isna(rank):
        return None
    position = int(float(rank)) - 1
    return 4 - int(np.floor(position * 5 / number_of_sa2s))


def read_table(tables_dir, filename):
    """Read one saved output table. A missing file stops the build, so the page is never built from partial results."""
    path = Path(tables_dir) / filename
    assert path.exists(), f"{path} not found; run the vibrancy_index.ipynb notebook first (see README)."
    return pd.read_csv(path)


def add_hotspot_columns(regions, tables_dir):
    """Add each SA2's neighbours' average score and local p-value from the saved hot-spot table."""
    columns = ["sa2_code", "p_value", "neighbour_average_score"]
    table = read_table(tables_dir, "vibrancy_hotspots.csv")[columns].copy()
    table["sa2_code"] = table["sa2_code"].astype(int)
    table = table.rename(columns={"p_value": "hotspot_p_value"})
    return regions.merge(table, on="sa2_code", how="left")


def add_school_group_counts(regions, tables_dir):
    """Add each SA2's share of the primary, high school and infants catchments, for the data map's hover text."""
    table = read_table(Path(tables_dir) / "map_layers", "school_group_counts.csv")
    table = table.rename(columns={group: f"schools_{group}" for group in SCHOOL_GROUPS})
    table["sa2_code"] = table["sa2_code"].astype(int)
    return regions.merge(table, on="sa2_code", how="left")


def raw_shapefile():
    """Return the SA2 boundary shapefile download_data.py already saved under raw/, from its manifest entry.

    Not a module-level constant: reading the manifest is real file I/O, and most tests never need the
    real shapefile (they pass their own small GeoDataFrame instead), so this only runs when a caller
    actually wants the default.
    """
    manifest_path = ROOT / "raw" / "manifest.json"
    assert manifest_path.exists(), f"{manifest_path} not found; run download_data.py first (see README)."
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asgs_source = manifest["sources"].get("asgs_sa2")
    assert asgs_source, "raw/manifest.json has no asgs_sa2 entry; run download_data.py to fetch the SA2 boundaries."
    folder = ROOT / asgs_source["extra"]["unzipped_to"]["main"]
    shapefiles = sorted(folder.glob("*.shp"))
    assert len(shapefiles) == 1, f"Expected one shapefile in {folder}, found {len(shapefiles)}."
    return shapefiles[0]


def load_regions(scores, shapefile=None):
    """Join saved scores to Greater Sydney SA2 boundaries and add CBD distance."""
    shapefile = raw_shapefile() if shapefile is None else shapefile
    score_rows = pd.read_csv(scores) if isinstance(scores, (str, Path)) else pd.DataFrame(scores).copy()
    score_rows["sa2_code"] = score_rows["sa2_code"].astype(int)
    bounds = gpd.read_file(shapefile, engine="pyogrio")
    bounds = bounds[bounds["GCC_NAME21"] == "Greater Sydney"].copy()
    bounds["sa2_code"] = bounds["SA2_CODE21"].astype(int)
    keep = ["sa2_code", "SA2_NAME21", "AREASQKM21", "geometry"]
    regions = bounds[keep].merge(score_rows, on="sa2_code", how="left")
    projected = regions.to_crs(METRIC_CRS)
    cbd = gpd.GeoSeries(gpd.points_from_xy([CBD_LON], [CBD_LAT]), crs=4326).to_crs(METRIC_CRS).iloc[0]
    regions["distance_km"] = projected.geometry.centroid.distance(cbd) / 1000
    regions["rank_class"] = regions["vibrancy_quintile"] - 1
    return regions


def top_fifth_stats(regions):
    """Return the headline area and resident shares for rank-fifth five."""
    scored = regions[regions["scored"] == True].copy()
    top = scored[scored["vibrancy_quintile"] == 5]
    return {
        "scored_sa2s": len(scored),
        "top_area_share": top["AREASQKM21"].sum() / scored["AREASQKM21"].sum(),
        "top_resident_share": top["residents"].sum() / scored["residents"].sum(),
    }


def headline_sentence(headline):
    """Return the page's headline sentence: the top quintile's share of the land and of the residents."""
    return (
        f"The most vibrant quintile of Sydney's SA2s covers "
        f"{headline['top_area_share']:.0%} of the land but holds "
        f"{headline['top_resident_share']:.0%} of its residents."
    )


def join_names(names):
    """Join names for a sentence: "A", "A and B", or "A, B and C"."""
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def outlier_sentence(scored, cluster, direction):
    """Say which SA2s form one outlier class, or return an empty string if there are none."""
    names = sorted(scored.loc[scored["hotspot_class"] == cluster, "sa2_name"])
    if not names:
        return ""
    verb = "scores" if len(names) == 1 else "score"
    return f"{join_names(names)} {verb} {direction}."


def moran_card_text(regions, global_i):
    """Return the Moran card's title and paragraphs. Every number and name comes from the data."""
    scored = regions[regions["scored"] == True]
    counts = {name: int((scored["hotspot_class"] == name).sum()) for name in HOTSPOT_ORDER}
    low_low = scored[scored["hotspot_class"] == "low-low"]
    resident_share = low_low["residents"].sum() / scored["residents"].sum()
    area_share = low_low["AREASQKM21"].sum() / scored["AREASQKM21"].sum()
    title = f"Neighbouring SA2s tend to score alike: {counts['high-high']} high-high and {counts['low-low']} low-low clusters"
    low_low_sentence = (
        f"The {counts['low-low']} low-low SA2s hold {resident_share:.1%} of residents but cover {area_share:.1%} "
        "of the land we scored"
    )
    if area_share > 2 * resident_share:
        low_low_sentence += ", so the group is mostly large, sparsely populated areas"
    outliers = " ".join(
        sentence for sentence in [
            outlier_sentence(scored, "high-low", "high among lower-scoring neighbours"),
            outlier_sentence(scored, "low-high", "low among higher-scoring ones"),
        ] if sentence
    )
    paragraphs = [
        "Moran's I asks whether neighbouring SA2s look alike. A value of 0 means no pattern and 1 means neighbours look "
        f"exactly alike; here it is {global_i:.2f}, so nearby SA2s often score alike, though that does not say why.",
        f"Of the {len(scored)} scored SA2s, {counts['high-high']} are high-high (a high score with high-scoring "
        f"neighbours) and {counts['low-low']} are low-low (a low score with low-scoring neighbours). "
        f"{outliers} The other {counts['not significant']} are not clusters.".replace("  ", " "),
        low_low_sentence + ".",
        "Clusters are descriptive: no correction is made for testing many areas, so some of them could appear by chance "
        "(the Limitations section explains this).",
    ]
    return {"title": title, "paragraphs": paragraphs}


def distance_group_median(scored, low, high):
    """Return one distance band's median score: the sorted values' middle-or-upper pick, matching the chart's own tick."""
    values = sorted(scored.loc[(scored["distance_km"] >= low) & (scored["distance_km"] < high), "vibrancy_score"])
    return values[len(values) // 2]


def distance_outer_exceptions(scored):
    """Return the distance chart's labelled outer exceptions: farther than 10 km, the top 3 by score.

    The same rule the interactive chart uses, so the static figure and the page always name the same SA2s.
    """
    outer = scored[scored["distance_km"] > DISTANCE_OUTER_KM]
    return outer.nlargest(DISTANCE_OUTER_COUNT, "vibrancy_score")


def distance_card_title(regions):
    """Return the distance chart's found title: the near-to-far median contrast and one named outer exception."""
    scored = regions[regions["scored"] == True]
    near = distance_group_median(scored, 0, 5)
    far = distance_group_median(scored, 40, np.inf)
    example = distance_outer_exceptions(scored).iloc[0]["sa2_name"]
    return (
        f"The median score falls from {near:.1f} near the centre to {far:.1f} beyond 40 km, "
        f"but a few centres such as {example} stand out from the trend"
    )


def histogram_card_title(scored, score_middle_share):
    """Return the histogram's found title: the middle-share fact, and the low-tail exception if there is one."""
    below = scored[scored["vibrancy_score"] < 70]
    title = f"Most SA2s sit close to the average: {score_middle_share:.0%} score within 10 points of 100"
    if below.empty:
        return title
    lowest = below.loc[below["vibrancy_score"].idxmin()]
    return (
        f"{title}, but {len(below)} score below 70, as low as {lowest['sa2_name']} "
        f"at {lowest['vibrancy_score']:.1f}"
    )


def zero_comparison(column_values):
    """Say how common a value of exactly zero is among the scored SA2s (the page's profile card says the same)."""
    zero_count = int((column_values == 0).sum())
    if zero_count == 1:
        return "none, as in no other SA2"
    share = zero_count / len(column_values) * 100
    if share < 1:
        return "none, as in fewer than 1% of SA2s"
    # Python's round() sends halves to the even number; the page rounds halves up, so do the same here.
    return f"none, as in {int(share + 0.5)}% of SA2s"


def total_count(density, area_km2):
    """Return the whole-number total behind a density (density times area), or None if either is missing.

    The saved densities are counts divided by area, so the product must be whole; fail loudly if it is not.
    """
    if pd.isna(density) or pd.isna(area_km2):
        return None
    product = float(density) * float(area_km2)
    total = round(product)
    assert abs(product - total) < 1e-6, f"{density} per km2 over {area_km2} km2 gives {product}, which is not whole"
    return total


def fact_total(row, column):
    """Return the total count behind one card fact: the residents column, or density times area."""
    if column == "residents_per_ha":
        return int(row["residents"])
    return total_count(row[column], row["area_km2"])


def density_comparison(column_values, value):
    """Say how a non-zero density compares with the scored SA2s, as the page's profile card does.

    From the 50th percentile up it is "higher than X%" (the share at or below the value); below that it is
    "lower than Y%" (the share strictly above it). Halves round up (Python's round() sends them to the even
    number, the page rounds them up), and 99 is the cap.
    """
    total = len(column_values)
    at_or_below = int((column_values <= value).sum())
    if at_or_below * 2 >= total:
        return f"higher than {min(99, int(at_or_below / total * 100 + 0.5))}% of SA2s"
    above = int((column_values > value).sum())
    return f"lower than {min(99, int(above / total * 100 + 0.5))}% of SA2s"


def card_facts(row, scored):
    """Return four card facts. A small density is shown as a total; the second line compares the density."""
    rows = []
    for label, column, (unit_one, unit_many), (noun_one, noun_many), limit in CARD_FACTS:
        value = float(row[column])
        if value < limit:
            total = fact_total(row, column)
            display = f"{total:,} {noun_one if total == 1 else noun_many} in total"
            if value == 0:
                comparison = zero_comparison(scored[column])
            else:
                comparison = "density " + density_comparison(scored[column], value)
        else:
            shown = int(value + 0.5)
            display = f"{shown:,} {unit_one if shown == 1 else unit_many}"
            if value >= scored[column].max():
                comparison = f"the highest of {len(scored)} SA2s"
            else:
                comparison = density_comparison(scored[column], value)
        rows.append({"label": label, "display": display, "percentile": comparison})
    return rows


def build_cards(regions):
    """Build the four approved place-card records from saved scores."""
    scored = regions[regions["scored"] == True].copy()
    cards = []
    for name in CARD_NAMES:
        match = scored[scored["sa2_name"] == name]
        if match.empty:
            continue
        row = match.iloc[0]
        pillars = []
        for label, column in [
            ("Intensity", "intensity_score"),
            ("Diversity", "diversity_score"),
            ("Design", "design_score"),
        ]:
            value = row[column]
            clipped = max(70, min(130, value)) if pd.notna(value) else None
            pillars.append({"label": label, "value": value, "clipped": clipped})
        texts = {
            "Darlinghurst": (
                "Its Intensity and Design bars are high and its Diversity bar is above average, so it is both "
                "dense and varied. The rank range shows that it stays near the top "
                "when the method changes."
            ),
            "Sydney (South) - Haymarket": (
                "It is dense and well connected, and its Diversity bar sits almost exactly on the "
                "Greater Sydney average, just above the line that makes a place count as diverse. A small "
                "change in the data could move it into the dense and less diverse group."
            ),
            "Gosford - Springfield": (
                "It has high Diversity without the same concentration of places as the leading "
                "inner-city SA2s. Its rank range is wide, so its place type says more about it than "
                "a single middle-table rank does."
            ),
            "Wetherill Park Industrial": (
                f'It has {int(row["businesses"]):,} registered businesses but only '
                f'{int(row["residents"]):,} residents. Its low rank shows that this screening '
                "score does not capture jobs or all the activity in an industrial estate."
            ),
        }
        cards.append(
            {
                "name": name,
                "place_type": row["place_type"],
                "score": row["vibrancy_score"],
                "rank": int(row["vibrancy_rank"]),
                "rank_min": int(row["rank_min"]),
                "rank_max": int(row["rank_max"]),
                "pillars": pillars,
                "facts": card_facts(row, scored),
                "text": texts[name],
            }
        )
    return cards


def rank_band_summary(scored):
    """Return rank-movement summaries and biggest movers for five rank quintiles."""
    ranked = scored.copy()
    ranked["rank_range"] = ranked["rank_max"] - ranked["rank_min"]
    rows = []
    for name, first, last in RANK_QUINTILES:
        band = ranked[ranked["vibrancy_rank"].between(first, last)].copy()
        if band.empty:
            rows.append({"label": f"{name} (0 SA2s)", "median": 0.0, "mean": 0.0,
                         "maximum": 0.0, "sa2s": 0, "mover_name": "",
                         "mover_rank_min": 0, "mover_rank_max": 0})
            continue
        band = band.sort_values(
            ["rank_range", "vibrancy_rank", "sa2_name"],
            ascending=[False, True, True],
        )
        mover = band.iloc[0]
        rows.append({
            "label": f"{name} ({len(band)} SA2s)",
            "median": float(band["rank_range"].median()),
            "mean": float(band["rank_range"].mean()),
            "maximum": float(mover["rank_range"]),
            "sa2s": int(len(band)),
            "mover_name": str(mover["sa2_name"]),
            "mover_rank_min": int(mover["rank_min"]),
            "mover_rank_max": int(mover["rank_max"]),
        })
    return rows


def chart_inputs(regions, tables_dir):
    """Collect compact tables used by the interactive SVG charts and controls."""
    ranks = read_table(tables_dir, "vibrancy_variant_ranks.csv")
    sensitivity = read_table(tables_dir, "vibrancy_sensitivity.csv")
    foot = read_table(tables_dir, "vibrancy_foot_traffic_sa2.csv")
    scored = regions[regions["scored"] == True].copy()
    foot = foot.merge(scored[["sa2_code", "vibrancy_score", "vibrancy_rank"]], on="sa2_code", how="left")
    density = (scored["intensity_score"] + scored["design_score"]) / 2
    correlations = {
        "intensity_design": float(scored["intensity_score"].rank().corr(scored["design_score"].rank())),
        "density_diversity": float(density.rank().corr(scored["diversity_score"].rank())),
    }
    return {"variant_ranks": ranks, "sensitivity": sensitivity, "foot_sites": foot,
            "correlations": correlations}


def limit_items(scored, foot_sites):
    """Return the five data-driven caveats shown in the Limits block."""
    hospital_values = scored.get("hospitals_per_km2", pd.Series(0, index=scored.index))
    no_hospital_share = (hospital_values == 0).mean()
    smallest_area = scored["AREASQKM21"].min()
    largest_area = scored["AREASQKM21"].max()
    lowest_diversity = scored.loc[scored["diversity_score"].idxmin()]
    lowest_name = str(lowest_diversity["sa2_name"])
    business_count = int(lowest_diversity["businesses"])
    return [
        "Business counts are registered businesses, and most are home-based, so they show "
        "where firms are registered, not shopfronts or jobs.",
        "There are no jobs, floor-area or building-age data, and hospitals are close to a "
        f"yes or no: {no_hospital_share:.0%} of scored SA2s have none.",
        "The inputs come from different dates, from 2021 to 2026, and scored SA2s differ "
        f"a lot in size, from {smallest_area:.1f} to {largest_area:,.1f} km².",
        "Extreme values are not capped: a few SA2s with very few businesses score very low "
        f"on Diversity, such as {lowest_name}, with {business_count:,} registered businesses.",
        "The score describes conditions that can support street activity, not how busy a place "
        f"is: measured walking counts exist for only {len(foot_sites)} inner-city SA2s.",
    ]


def squares_svg(total, highlighted, description):
    """Return an inline SVG of `total` squares, row by row, with the squares at the `highlighted` positions marked."""
    rows = math.ceil(total / GRID_COLUMNS)
    squares = []
    for position in range(total):
        x = (position % GRID_COLUMNS) * GRID_STEP
        y = (position // GRID_COLUMNS) * GRID_STEP
        css_class = "square on" if position in highlighted else "square"
        squares.append(f'<rect class="{css_class}" x="{x}" y="{y}" width="{GRID_SQUARE}" height="{GRID_SQUARE}" rx="2"/>')
    width = GRID_COLUMNS * GRID_STEP
    height = rows * GRID_STEP
    return (f'<svg class="squares" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{html.escape(description)}">' + "".join(squares) + "</svg>")


def walking_count_positions(foot_sites):
    """Return the square positions (rank minus one) of the SA2s that have walking counts."""
    return {int(rank) - 1 for rank in foot_sites["vibrancy_rank"].dropna()}


def chance_positions(scored_sa2s):
    """Return the square positions marked in the chance picture, the same ones on every build."""
    by_chance = round(CHANCE_LEVEL * scored_sa2s)
    return set(random.Random(CHANCE_SEED).sample(range(scored_sa2s), by_chance))


def walking_count_squares(scored_sa2s, foot_sites):
    """Return the picture and its caption for the SA2s that have walking counts, shown among all scored SA2s in rank order."""
    ranks = sorted(int(rank) for rank in foot_sites["vibrancy_rank"].dropna())
    if not ranks:
        return squares_svg(scored_sa2s, set(), "No SA2s have walking counts."), "No SA2s have walking counts."
    highlighted = walking_count_positions(foot_sites)
    description = (f"{len(ranks)} of {scored_sa2s} scored SA2s have walking counts. "
                   f"All of them are ranked {ranks[0]} to {ranks[-1]}.")
    caption = (f"{len(ranks)} of the {scored_sa2s} scored SA2s have walking counts, and all of them rank "
               f"{ranks[0]} to {ranks[-1]}. The other {scored_sa2s - len(ranks)} could not be checked this way.")
    return squares_svg(scored_sa2s, highlighted, description), caption


def chance_squares(scored_sa2s):
    """Return the picture and its caption for how many tests pass by chance alone, with squares placed at random."""
    by_chance = round(CHANCE_LEVEL * scored_sa2s)
    highlighted = chance_positions(scored_sa2s)
    description = f"{by_chance} of {scored_sa2s} squares are marked, placed at random."
    caption = (f"Illustration only: {scored_sa2s} squares for {scored_sa2s} tests, with {by_chance} marked at "
               f"random. The squares are not real SA2s.")
    return squares_svg(scored_sa2s, highlighted, description), caption, by_chance


def place_type_split_counts(place_types):
    """Return the two counts behind panel 3's found title: dense-and-diverse SA2s, and dense-and-less-diverse ones."""
    dense_diverse = int(place_types.loc[place_types["place_type"] == "dense and diverse", "sa2s"].iloc[0])
    dense_less = int(place_types.loc[place_types["place_type"] == "dense and less diverse", "sa2s"].iloc[0])
    return dense_diverse, dense_less


def place_type_split_title(dense_diverse, dense_less):
    """Return panel 3's found title, built from the same two counts the page puts in its own heading."""
    return f"Dense places split in two: {dense_diverse} have a varied mix of businesses and land uses and {dense_less} do not"


def equity_income_shares(equity):
    """Return the top-quintile resident share of the higher- and lower-income groups, as percentages."""
    indexed = equity.set_index("income_group")
    high = indexed.loc["higher-income areas", "top_quintile_share"] * 100 if "higher-income areas" in indexed.index else 0
    low = indexed.loc["lower-income areas", "top_quintile_share"] * 100 if "lower-income areas" in indexed.index else 0
    return high, low


def equity_card_title(high, low):
    """Return panel 5's found title: the top-quintile share gap between the highest and lowest income groups."""
    return (
        "Residents of higher-income areas are about twice as likely to live in a "
        f"top-quintile SA2 ({high:.0f}% against {low:.0f}%)"
    )


def foot_traffic_spearman(foot, day):
    """Return one day's Spearman correlation between the score and the measured walking counts."""
    return float(foot.loc[foot["day_type"] == day, "spearman"].iloc[0])


def foot_traffic_day_title(foot, day):
    """Return the found title of one day's foot-traffic scatter, the interactive panel's own heading."""
    return f"{day.capitalize()} counts have only a weak link with the score (Spearman {foot_traffic_spearman(foot, day):.2f})"


def compute_stats(regions, tables_dir=OUTPUT_DIR):
    """Collect every page number from saved score and analysis outputs."""
    headline = top_fifth_stats(regions)
    scored = regions[regions["scored"] == True].copy()
    rank_counts = [int((scored["rank_class"] == value).sum()) for value in range(5)]
    layers = layer_definitions(regions)
    equity = read_table(tables_dir, "vibrancy_equity.csv")
    sensitivity = read_table(tables_dir, "vibrancy_sensitivity.csv")
    hotspots = read_table(tables_dir, "vibrancy_hotspot_global.csv")
    place_types = read_table(tables_dir, "vibrancy_place_types.csv")
    foot = read_table(tables_dir, "vibrancy_foot_traffic_check.csv")
    chart = chart_inputs(regions, tables_dir)
    top_overlap = sensitivity["top_25_overlap"]
    stats = {"headline": headline, "rank_counts": rank_counts, "equity": equity, "place_types": place_types,
             "cards": build_cards(regions), "median_rank_range": float((scored["rank_max"] - scored["rank_min"]).median()),
             "top_overlap_min": int(top_overlap.min()),
             "top_overlap_max": int(top_overlap.max()),
             "global_i": float(hotspots.iloc[0]["global_morans_i"]),
             "global_p": float(hotspots.iloc[0]["p_value"]),
             "foot": foot, "score_labels": score_fifth_labels(scored),
             "score_middle_share": float(((scored["vibrancy_score"] >= 90) & (scored["vibrancy_score"] < 110)).mean()),
             "rank_bands": rank_band_summary(scored), "layers": layers,
             "built_up_bounds": START_VIEW, "map_caption": map_caption(regions, headline),
             "chart": chart, "limits": limit_items(scored, chart["foot_sites"]),
             "total_sa2s": len(regions)}
    stats["moran"] = moran_card_text(regions, stats["global_i"])
    stats["distance"] = {"title": distance_card_title(regions)}
    stats["histogram"] = {"title": histogram_card_title(scored, stats["score_middle_share"])}
    stats["headline_title"] = headline_sentence(headline)
    dense_diverse_count, dense_less_count = place_type_split_counts(place_types)
    stats["dense_diverse_count"] = dense_diverse_count
    stats["dense_less_count"] = dense_less_count
    stats["place_type_title"] = place_type_split_title(dense_diverse_count, dense_less_count)
    equity_high, equity_low = equity_income_shares(equity)
    stats["equity_high"] = equity_high
    stats["equity_low"] = equity_low
    stats["equity_title"] = equity_card_title(equity_high, equity_low)
    stats["foot_titles"] = {day: foot_traffic_day_title(foot, day) for day in ["weekday", "weekend"]}
    return stats


def score_fifth_labels(scored):
    """Return one-decimal score-range labels for the five ranking fifths of the overall score."""
    return quintile_labels(scored["vibrancy_score"])


def quintile_labels(values):
    """Return one-decimal range labels for the five quintiles of a column of scores, top first."""
    low, middle_low, middle_high, high = values.quantile([0.2, 0.4, 0.6, 0.8]).to_list()
    return [
        f"Top quintile: {high:.1f} and above",
        f"Second quintile: {middle_high:.1f} to under {high:.1f}",
        f"Middle quintile: {middle_low:.1f} to under {middle_high:.1f}",
        f"Fourth quintile: {low:.1f} to under {middle_low:.1f}",
        f"Bottom quintile: under {low:.1f}",
    ]


def layer_definitions(regions):
    """Return the name, key labels and counts for each of the six interactive map layers."""
    scored = regions[regions["scored"] == True].copy()
    layers = {}
    score_layers = {
        "overall": ("Overall score", "vibrancy_score"),
        "intensity": ("Intensity", "intensity_score"),
        "diversity": ("Diversity", "diversity_score"),
        "design": ("Design", "design_score"),
    }
    for key, (name, column) in score_layers.items():
        available = scored[column].dropna()
        ranks = available.rank(ascending=False, method="first")
        classes = ranks.map(lambda value: rank_class(value, len(available)))
        layers[key] = {"name": name, "labels": quintile_labels(available),
                       "counts": [int((classes == value).sum()) for value in range(4, -1, -1)],
                       "unavailable": int(scored[column].isna().sum())}
    type_counts = scored["place_type"].value_counts()
    layers["place_types"] = {
        "name": "Place types",
        "labels": list(PLACE_COLORS),
        "counts": [int(type_counts.get(name, 0)) for name in PLACE_COLORS],
        "unavailable": 0,
    }
    hotspot_counts = scored["hotspot_class"].value_counts()
    layers["hotspots"] = {
        "name": "Hot spots",
        "labels": [HOTSPOT_NAMES[name] for name in HOTSPOT_ORDER],
        "counts": [int(hotspot_counts.get(name, 0)) for name in HOTSPOT_ORDER],
        "unavailable": 0,
    }
    return layers


def map_caption(regions, headline):
    """Return the data-led main-map caption and outer top-fifth examples."""
    top = regions[(regions["scored"] == True) & (regions["vibrancy_quintile"] == 5)]
    outer = top[top["distance_km"] > 10].sort_values("vibrancy_rank")
    outer_names = join_names(outer["sa2_name"].head(4).tolist())
    return {"outer_count": int(len(outer)), "outer_names": outer_names, "top_count": int(len(top)),
            "area_share": headline["top_area_share"], "resident_share": headline["top_resident_share"]}


def assert_figure_text_layout(fig):
    """Assert that visible figure text is in bounds and does not overlap."""
    from matplotlib.text import Text
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    figure_box = fig.bbox
    boxes = []
    for artist in fig.findobj(match=Text):
        if not artist.get_visible() or not artist.get_text():
            continue
        box = artist.get_window_extent(renderer)
        if box.width and box.height:
            in_bounds = figure_box.contains(box.x0, box.y0) and figure_box.contains(box.x1, box.y1)
            assert in_bounds, f"Text outside figure: {artist.get_text()}"
            boxes.append((artist.get_text(), box))
    for position, (first_text, first) in enumerate(boxes):
        for second_text, second in boxes[position + 1:]:
            assert not first.overlaps(second), f"Text overlaps: {first_text} / {second_text}"


def save_figure(fig, out_dir, filename, bbox_inches=None):
    """Check the figure's text layout, save it as images/<filename> and close it. Return the saved path."""
    import matplotlib.pyplot as plt
    assert_figure_text_layout(fig)
    path = Path(out_dir) / "images" / filename
    fig.savefig(path, dpi=180, bbox_inches=bbox_inches)
    plt.close(fig)
    return path


def hide_axes(axis):
    """Remove a map axis's ticks and frame."""
    axis.set_xticks([])
    axis.set_yticks([])
    for spine in axis.spines.values():
        spine.set_visible(False)


def quiet_axes(axis):
    """Apply light gridlines and quiet axes to a matplotlib axis."""
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.spines["bottom"].set_color("#c3c2b7")
    axis.grid(axis="y", color="#e1e0d9", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.tick_params(length=0, colors="#52514e")


def outline_style(hotspot):
    """Return the matplotlib line style of one hot-spot class, from the page's dash pattern."""
    dash = tuple(int(value) for value in HOTSPOT_STYLES[hotspot]["dash"].split())
    return (0, dash) if dash else "solid"


def lighten_color(hex_color, amount):
    """Return a hex colour blended toward white by a fraction (0 unchanged, 1 white), like the page's own tint().

    Round-half-up, matching the page's Math.round and this file's own convention (see zero_comparison), not
    Python's round(), which would send a half to the nearest even number.
    """
    channels = [int(hex_color[start:start + 2], 16) for start in (1, 3, 5)]
    lightened = [int(channel + (255 - channel) * amount + 0.5) for channel in channels]
    return "#{:02x}{:02x}{:02x}".format(*lightened)


def built_up_frame():
    """Return the page's starting frame (START_VIEW) as four corners in the metric CRS."""
    (south, west), (north, east) = START_VIEW
    corners = gpd.GeoSeries(gpd.points_from_xy([west, east, east, west], [south, south, north, north]), crs=4326)
    return [(point.x, point.y) for point in corners.to_crs(METRIC_CRS)]


def draw_regions(axis, projected, column, colors, edge_width, ramp=RAMP):
    """Fill every SA2: rank fifths or a colour per group, grey for an SA2 with no value, and hollow if it has no score."""
    unscored = projected[projected["scored"] != True]
    if len(unscored):
        unscored.plot(ax=axis, facecolor="none", edgecolor=NOT_SCORED_OUTLINE, linewidth=0.6)
    scored = projected[projected["scored"] == True]
    if column == "rank_class":
        fill = [ramp[int(value)] if pd.notna(value) else UNAVAILABLE_COLOR for value in scored[column]]
    else:
        fill = [colors.get(value, UNAVAILABLE_COLOR) for value in scored[column]]
    scored.plot(ax=axis, color=fill, edgecolor="#fcfcfb", linewidth=edge_width)


def draw_outlines(axis, projected):
    """Draw the hot-spot outlines thinly and return the classes that have at least one SA2."""
    scored = projected[projected["scored"] == True]
    drawn = []
    for hotspot in HOTSPOT_STYLES:
        subset = scored[scored["hotspot_class"] == hotspot]
        if len(subset):
            subset.boundary.plot(ax=axis, color=HOTSPOT_COLOR, linewidth=STATIC_OUTLINE_WIDTH,
                                 linestyle=outline_style(hotspot), alpha=STATIC_OUTLINE_ALPHA)
            drawn.append(hotspot)
    return drawn


def grey_key_swatch(label):
    """Return a key entry for the grey fill of an SA2 with no value for the layer ("Not available")."""
    from matplotlib.patches import Patch
    return Patch(facecolor=UNAVAILABLE_COLOR, edgecolor=MUTED_COLOR, linewidth=0.8, label=label)


def hollow_key_swatch(label):
    """Return a key entry for an SA2 that is not scored: no fill and a thin dark outline, as on the page."""
    from matplotlib.patches import Patch
    return Patch(facecolor="none", edgecolor=NOT_SCORED_OUTLINE, linewidth=0.6, label=label)


def outline_key_entries(drawn):
    """Return a key header and one line entry for each outline class that is drawn."""
    from matplotlib.lines import Line2D
    entries = [Line2D([], [], linestyle="none", linewidth=0, label=OUTLINE_KEY_HEADER)]
    for hotspot in drawn:
        entries.append(Line2D([], [], color=HOTSPOT_COLOR, linewidth=STATIC_OUTLINE_WIDTH, alpha=STATIC_OUTLINE_ALPHA,
                              linestyle=outline_style(hotspot), label=OUTLINE_KEY_LABELS[hotspot]))
    return entries


def save_two_panel_map(regions, column, colors, title, filename, out_dir, key_entries, outlines=False):
    """Save a map as two panels, the whole region (small) and the built-up frame (large), with one shared key."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    projected = regions.to_crs(METRIC_CRS).copy()
    frame = built_up_frame()
    fig, (whole, built_up) = plt.subplots(1, 2, figsize=(12.5, 7.4), dpi=180, gridspec_kw={"width_ratios": [1, 1.7]})
    drawn = []
    for axis, edge_width in [(whole, 0.15), (built_up, 0.25)]:
        draw_regions(axis, projected, column, colors, edge_width)
        if outlines:
            drawn = draw_outlines(axis, projected)
    whole.add_patch(Polygon(frame, closed=True, fill=False, edgecolor=HOTSPOT_COLOR, linewidth=0.8))
    built_up.set_xlim(min(x for x, _ in frame), max(x for x, _ in frame))
    built_up.set_ylim(min(y for _, y in frame), max(y for _, y in frame))
    whole.set_title("Greater Sydney", loc="left", fontsize=11, fontweight="bold")
    built_up.set_title("The built-up area", loc="left", fontsize=11, fontweight="bold")
    for axis in (whole, built_up):
        axis.set_anchor("N")
        hide_axes(axis)
    fig.suptitle(title, x=0.01, ha="left", fontsize=14, fontweight="bold")
    entries = key_entries + (outline_key_entries(drawn) if outlines else [])
    legend = fig.legend(handles=entries, loc="lower center", ncol=2, frameon=False, fontsize=9)
    for label in legend.get_texts():
        if label.get_text() == OUTLINE_KEY_HEADER:
            label.set_fontweight("bold")
    key_rows = (len(entries) + 1) // 2
    fig.tight_layout(rect=(0, 0.03 + 0.028 * key_rows, 1, 0.965))
    return save_figure(fig, out_dir, filename, bbox_inches="tight")


def save_map(regions, column, filename, title, out_dir, key_entries, note=None, ramp=RAMP):
    """Save one single-panel rank-fifth map with a small key for its grey fills."""
    import matplotlib.pyplot as plt
    projected = regions.to_crs(METRIC_CRS).copy()
    fig, axis = plt.subplots(figsize=(9, 7), dpi=180)
    axis.set_title(title, loc="left", fontsize=14, fontweight="bold", pad=12)
    draw_regions(axis, projected, column, {}, 0.25, ramp)
    if key_entries:
        axis.legend(handles=key_entries, loc="upper center", bbox_to_anchor=(0.5, -0.03), ncol=2, frameon=False, fontsize=9)
    if note:
        axis.text(0.02, 0.02, note, transform=axis.transAxes, fontsize=9, color="#52514e")
    hide_axes(axis)
    fig.tight_layout()
    return save_figure(fig, out_dir, filename, bbox_inches="tight")


def figure_main_map(regions, stats, out_dir):
    """Save the main map: rank fifths and hot-spot outlines, whole region beside the built-up frame."""
    from matplotlib.patches import Patch
    fifths = [Patch(facecolor=RAMP[4 - index], edgecolor="none", label=label) for index, label in enumerate(stats["score_labels"])]
    return save_two_panel_map(regions, "rank_class", {}, stats["headline_title"], "vibrancy_map.png", out_dir,
                              fifths + [hollow_key_swatch("Not scored")], outlines=True)


def figure_place_types(regions, stats, out_dir):
    """Save the place-type map: four colours, whole region beside the built-up frame."""
    from matplotlib.patches import Patch
    types = [Patch(facecolor=color, edgecolor="none", label=name) for name, color in PLACE_COLORS.items()]
    return save_two_panel_map(regions, "place_type", PLACE_COLORS, stats["place_type_title"], "vibrancy_place_types.png",
                              out_dir, types + [hollow_key_swatch("Not scored")])


def figure_pillars(regions, out_dir):
    """Save rank-fifth maps for the three pillar scores, explaining every grey fill."""
    paths = []
    for column, label, filename in [
        ("intensity_z", "Intensity", "vibrancy_intensity_map.png"),
        ("diversity_z", "Diversity", "vibrancy_diversity_map.png"),
        ("design_z", "Design", "vibrancy_design_map.png"),
    ]:
        copy = regions.copy()
        scored = copy[copy["scored"] == True]
        pillar_rank = scored[column].rank(ascending=False, method="first")
        number_ranked = int(pillar_rank.notna().sum())
        copy["rank_class"] = np.nan
        copy.loc[scored.index, "rank_class"] = pillar_rank.map(lambda value: rank_class(value, number_ranked))
        key_entries = []
        not_available = int(scored[column].isna().sum())
        if not_available:
            key_entries.append(grey_key_swatch(f"Not available ({not_available})"))
        key_entries.append(hollow_key_swatch("Not scored"))
        ramp = [COLOR_ROLES["light"][f"{PILLAR_CSS_NAME[label]}-{step}"] for step in range(1, 6)]
        paths.append(save_map(copy, "rank_class", filename, f"{label} by rank quintile", out_dir, key_entries,
                              note=f"Darker = higher quintile of {label}", ramp=ramp))
    return paths


def figure_equity(stats, out_dir):
    """Save paired top- and bottom-quintile equity bars."""
    import matplotlib.pyplot as plt
    equity = stats["equity"].copy()
    fig, axis = plt.subplots(figsize=(11, 4.8), dpi=180)
    positions = np.arange(len(equity))
    width = 0.34
    top_bars = axis.bar(positions - width / 2, equity["top_quintile_share"] * 100, width, label="Top quintile", color=RAMP[-1])
    bottom_bars = axis.bar(positions + width / 2, equity["bottom_quintile_share"] * 100, width,
                           label="Bottom quintile", color="#b8b8b4")
    axis.set_xticks(positions, equity["income_group"].str.replace(" areas", ""))
    axis.set_xlabel("Median income group")
    axis.set_ylabel("Share of residents (%)")
    axis.set_title(stats["equity_title"], loc="left", fontsize=12, fontweight="bold")
    highest = max(equity["top_quintile_share"].max(), equity["bottom_quintile_share"].max()) * 100
    axis.set_ylim(0, highest * 1.18)
    axis.set_yticks(np.arange(0, int(highest) + 1, 10))
    for bars in [top_bars, bottom_bars]:
        axis.bar_label(bars, labels=[f"{value:.1f}" for value in bars.datavalues], padding=3, fontsize=9)
    axis.legend(frameon=False)
    quiet_axes(axis)
    fig.tight_layout()
    return save_figure(fig, out_dir, "vibrancy_equity.png")


def figure_rank_ranges(stats, out_dir):
    """Save median and maximum rank movement for the five baseline quintiles, each bar in its own quintile colour."""
    import matplotlib.pyplot as plt
    bands = stats["rank_bands"]
    labels = [band["label"] for band in bands]
    medians = [band["median"] for band in bands]
    maximums = [band["maximum"] for band in bands]
    # Bands run top to bottom quintile, in the same order as the map's ramp, darkest first (matching the page's own tint()).
    median_colors = [RAMP[4 - index] for index in range(len(bands))]
    maximum_colors = [lighten_color(color, RANK_RANGE_TINT_AMOUNT) for color in median_colors]
    fig, axis = plt.subplots(figsize=(10, 4.5), dpi=180)
    axis.barh(labels, maximums, height=0.22, color=maximum_colors)
    bars = axis.barh(labels, medians, height=0.54, color=median_colors)
    axis.bar_label(bars, labels=[f"median {value:.0f} places" for value in medians], padding=4, fontsize=9)
    for position, band in enumerate(bands):
        mover = f'{band["mover_name"]}\nswings {band["mover_rank_min"]} to {band["mover_rank_max"]}'
        axis.text(band["maximum"] - 3, position, mover, ha="right", va="center", fontsize=8)
    axis.invert_yaxis()
    axis.set_xlim(0, max(maximums) * 1.04)
    axis.set_xticks(np.arange(0, 301, 50))
    axis.set_xlabel("Median movement in rank across 22 variants")
    axis.set_ylabel("Baseline rank quintile")
    axis.set_title("Middle-ranked SA2s move furthest across variants", loc="left", fontsize=13, fontweight="bold")
    quiet_axes(axis)
    fig.tight_layout()
    return save_figure(fig, out_dir, "vibrancy_rank_ranges.png")


def padded_score_range(values):
    """Round a range of scores out to the nearest ten, with a margin of four, like the page's axes."""
    lower = math.floor((min(values) - 4) / 10) * 10
    upper = math.ceil((max(values) + 4) / 10) * 10
    return lower, upper


def chart_axes(axis, vertical_grid=False):
    """Apply the quiet axes, with the x tick labels set lower so they clear the y tick label at the corner."""
    quiet_axes(axis)
    axis.tick_params(axis="x", pad=8)
    if vertical_grid:
        axis.grid(axis="x", color="#e1e0d9", linewidth=0.8)


def sa2_count(count):
    """Return "1 SA2" or "5 SA2s"."""
    return f"{count} SA2" if count == 1 else f"{count} SA2s"


def add_note(fig, note):
    """Write a small note along the bottom of a figure."""
    fig.text(0.01, 0.01, textwrap.fill(note, 130), fontsize=8, color="#52514e", va="bottom")


def label_dots(fig, axis, dots):
    """Write each dot's name beside it, at the first corner where it overlaps no other text and stays inside the axes.

    `dots` is a list of (x, y, name) in data coordinates. A name with no free corner is left out, as on the page.
    """
    from matplotlib import patheffects
    halo = [patheffects.withStroke(linewidth=2.5, foreground="white")]
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_box = axis.get_window_extent(renderer)
    taken = [text.get_window_extent(renderer) for text in axis.texts]
    for x, y, name in dots:
        for x_offset, y_offset, horizontal, vertical in LABEL_OFFSETS:
            label = axis.annotate(name, (x, y), xytext=(x_offset, y_offset), textcoords="offset points",
                                  ha=horizontal, va=vertical, fontsize=8, path_effects=halo)
            box = label.get_window_extent(renderer)
            inside = axes_box.contains(box.x0, box.y0) and axes_box.contains(box.x1, box.y1)
            if inside and not any(box.overlaps(other) for other in taken):
                taken.append(box)
                break
            label.remove()


def figure_distance(regions, stats, out_dir):
    """Save the distance chart: one column of dots per distance group, with the group median and three named centres."""
    import matplotlib.pyplot as plt
    scored = regions[regions["scored"] == True]
    named = set(distance_outer_exceptions(scored)["sa2_name"])
    rng = np.random.default_rng(DOT_SEED)
    fig, axis = plt.subplots(figsize=(10, 5.6), dpi=180)
    names = []
    tick_labels = []
    for position, (low, high, band_name) in enumerate(DISTANCE_BANDS):
        band = scored[(scored["distance_km"] >= low) & (scored["distance_km"] < high)]
        if band.empty:
            tick_labels.append(f"{band_name}\nn = 0")
            continue
        across = position + rng.uniform(-0.3, 0.3, len(band))
        up = band["vibrancy_score"].clip(lower=SCORE_AXIS_LOW)
        axis.scatter(across, up, s=DOT_SIZE, color=[RAMP[int(value)] for value in band["rank_class"]], linewidths=0)
        median = distance_group_median(scored, low, high)
        axis.hlines(median, position - 0.36, position + 0.36, color="#52514e", linewidth=1.6)
        tick_labels.append(f"{band_name}\nmedian {median:.1f}\nn = {len(band)}")
        for x, y, name in zip(across, up, band["sa2_name"]):
            if name in named:
                names.append((x, y, name))
    axis.axhline(100, color=GUIDE_COLOR, linewidth=1, linestyle="--")
    axis.text(-0.55, 100.8, "Greater Sydney average, 100", ha="left", fontsize=8, color="#52514e")
    axis.set_xticks(range(len(DISTANCE_BANDS)), tick_labels)
    axis.set_xlim(-0.6, len(DISTANCE_BANDS) - 0.4)
    axis.set_ylim(SCORE_AXIS_LOW, SCORE_AXIS_HIGH)
    axis.set_yticks([70, 85, 100, 115, 130])
    axis.set_xlabel("Distance from the CBD (km)")
    axis.set_ylabel("Vibrancy score")
    axis.set_title(textwrap.fill(stats["distance"]["title"], TITLE_WIDTH), loc="left", fontsize=12, fontweight="bold")
    chart_axes(axis)
    below = int((scored["vibrancy_score"] < SCORE_AXIS_LOW).sum())
    note = f"Each dot is one SA2, placed by the straight-line distance from the Sydney GPO to its centre. Dots take the colour of their quintile, and the bar is the group's median. {sa2_count(below)} below 70 sit on the bottom edge."
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    add_note(fig, note)
    label_dots(fig, axis, names)
    return save_figure(fig, out_dir, "vibrancy_distance.png")


def figure_histogram(regions, stats, out_dir):
    """Save the histogram of scores in two-point bins, each bar in the quintile colour of its middle score."""
    import matplotlib.pyplot as plt
    scores = regions.loc[regions["scored"] == True, "vibrancy_score"]
    starts = list(range(SCORE_AXIS_LOW, SCORE_AXIS_HIGH, HISTOGRAM_BIN))
    counts = [int(((scores >= start) & (scores < start + HISTOGRAM_BIN)).sum()) for start in starts]
    colors = []
    for start in starts:
        higher = int((scores > start + HISTOGRAM_BIN / 2).sum()) + 1
        colors.append(RAMP[rank_class(higher, len(scores))])
    top = math.ceil(max(counts) / 10) * 10
    fig, axis = plt.subplots(figsize=(10, 5), dpi=180)
    axis.bar([start + HISTOGRAM_BIN / 2 for start in starts], counts, width=HISTOGRAM_BIN - 0.2, color=colors)
    median = float(sorted(scores)[len(scores) // 2])
    axis.vlines(median, 0, top * 1.05, color="#52514e", linewidth=1.2)
    axis.text(median, top * 1.07, f"median {median:.1f}", ha="center", fontsize=9)
    bracket = top * 1.2
    axis.plot([90, 90, 110, 110], [bracket - top * 0.04, bracket, bracket, bracket - top * 0.04], color="#52514e", linewidth=1.2)
    axis.text(100, bracket + top * 0.02, f"{stats['score_middle_share']:.0%} of SA2s", ha="center", fontsize=9)
    axis.set_xlim(SCORE_AXIS_LOW, SCORE_AXIS_HIGH)
    axis.set_ylim(0, top * 1.32)
    axis.set_yticks(range(0, top + 1, 10))
    axis.set_xlabel("Vibrancy score")
    axis.set_ylabel("SA2s in the bin")
    axis.set_title(textwrap.fill(stats["histogram"]["title"], TITLE_WIDTH), loc="left", fontsize=12, fontweight="bold")
    chart_axes(axis)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    add_note(fig, "Each bar counts the SA2s whose score falls in a two-point range. The bracket marks 90 to 110, within 10 points of the Greater Sydney average of 100.")
    return save_figure(fig, out_dir, "vibrancy_histogram.png")


def figure_moran(regions, stats, out_dir):
    """Save the Moran scatterplot: each SA2's score against its neighbours' average, coloured by cluster class."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    scored = regions[(regions["scored"] == True) & regions["neighbour_average_score"].notna()]
    below = scored[scored["vibrancy_score"] < MORAN_AXIS_LOW]
    plotted = scored[scored["vibrancy_score"] >= MORAN_AXIS_LOW]
    x_high = padded_score_range(scored["vibrancy_score"])[1]
    y_low, y_high = padded_score_range(plotted["neighbour_average_score"])
    moran_i = stats["global_i"]
    fig, axis = plt.subplots(figsize=(9, 6.6), dpi=180)
    axis.axvline(100, color=GUIDE_COLOR, linewidth=1, linestyle="--")
    axis.axhline(100, color=GUIDE_COLOR, linewidth=1, linestyle="--")
    # The clusters are drawn first and the plain dots last, so the plain dots do not hide them.
    for hotspot in reversed(HOTSPOT_ORDER):
        group = plotted[plotted["hotspot_class"] == hotspot]
        alpha = 0.55 if hotspot == "not significant" else 1
        color = COLOR_ROLES["light"][HOTSPOT_CSS_NAME[hotspot]]
        axis.scatter(group["vibrancy_score"], group["neighbour_average_score"], s=DOT_SIZE * 1.4, color=color,
                     alpha=alpha, linewidths=0, zorder=3)
    line_x = np.array([MORAN_AXIS_LOW, x_high])
    axis.plot(line_x, 100 + moran_i * (line_x - 100), color="#0b0b0b", linewidth=1.2, zorder=4)
    axis.text(0.99, 0.98, "High-high", transform=axis.transAxes, ha="right", va="top", fontsize=9)
    axis.text(0.01, 0.98, "Low-high", transform=axis.transAxes, ha="left", va="top", fontsize=9)
    axis.text(0.01, 0.02, "Low-low", transform=axis.transAxes, ha="left", va="bottom", fontsize=9)
    axis.text(0.99, 0.02, "High-low", transform=axis.transAxes, ha="right", va="bottom", fontsize=9)
    axis.set_xlim(MORAN_AXIS_LOW, x_high)
    axis.set_ylim(y_low, y_high)
    axis.set_xticks(range(MORAN_AXIS_LOW, x_high + 1, 10))
    axis.set_yticks(range(y_low, y_high + 1, 10))
    axis.set_xlabel("Vibrancy score")
    axis.set_ylabel("Average score of neighbouring SA2s")
    axis.set_title(textwrap.fill(stats["moran"]["title"], 75), loc="left", fontsize=12, fontweight="bold")
    chart_axes(axis, vertical_grid=True)
    key = [Line2D([], [], marker="o", linestyle="none", markersize=6, label=HOTSPOT_NAMES[hotspot],
                  color=COLOR_ROLES["light"][HOTSPOT_CSS_NAME[hotspot]]) for hotspot in HOTSPOT_ORDER]
    fig.legend(handles=key, loc="lower center", ncol=2, frameon=False, fontsize=8, bbox_to_anchor=(0.5, 0.045))
    fig.tight_layout(rect=(0, 0.16, 1, 1))
    note = f"Each dot is one SA2, and neighbours are SA2s that share a border or corner. The black line has a slope of {moran_i:.2f}, which is Moran's I."
    if len(below):
        note += f" {sa2_count(len(below))} below {MORAN_AXIS_LOW} not drawn: " + join_names(below["sa2_name"].tolist()) + "."
    add_note(fig, note)
    return save_figure(fig, out_dir, "vibrancy_moran.png")


def scatter_dots(axis, x_values, y_values, scored, y_low, y_high):
    """Draw every SA2 in its quintile colour. Return the SA2s to name: the four examples, then the top three of each quintile."""
    names = [name for name in CARD_NAMES if name in set(scored["sa2_name"])]
    for quintile in range(5, 0, -1):
        top = scored[scored["vibrancy_quintile"] == quintile].nlargest(3, "vibrancy_score")["sa2_name"]
        names += [name for name in top if name not in names]
    dots = []
    for code in x_values.index:
        y = y_values[code]
        if y < y_low or y > y_high:
            continue
        row = scored.loc[code]
        axis.scatter([x_values[code]], [y], s=DOT_SIZE, color=RAMP[int(row["rank_class"])], linewidths=0)
        if row["sa2_name"] in names:
            dots.append((x_values[code], y, row["sa2_name"]))
    return sorted(dots, key=lambda dot: names.index(dot[2]))


def figure_intensity_design(regions, stats, out_dir):
    """Save the Intensity against Design scatterplot, with the four example places named."""
    import matplotlib.pyplot as plt
    scored = regions[(regions["scored"] == True)].dropna(subset=["intensity_score", "design_score"]).set_index("sa2_code")
    x_low, x_high = padded_score_range(scored["intensity_score"])
    y_low, y_high = padded_score_range(scored["design_score"])
    fig, axis = plt.subplots(figsize=(8.5, 6.4), dpi=180)
    named = scatter_dots(axis, scored["intensity_score"], scored["design_score"], scored, y_low, y_high)
    axis.set_xlim(x_low, x_high)
    axis.set_ylim(y_low, y_high)
    axis.set_xlabel("Intensity score")
    axis.set_ylabel("Design score")
    axis.set_title("Intensity against Design", loc="left", fontsize=12, fontweight="bold")
    chart_axes(axis, vertical_grid=True)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    correlation = stats["chart"]["correlations"]["intensity_design"]
    add_note(fig, f"Dots take the colour of their quintile; the four example places and the top three of each quintile are named. Spearman correlation: {correlation:.2f} (1 would mean the two pillars rank the SA2s in exactly the same order).")
    label_dots(fig, axis, named)
    return save_figure(fig, out_dir, "vibrancy_intensity_design.png")


def figure_density_diversity(regions, stats, out_dir):
    """Save the Density against Diversity scatterplot, split at 100 into the four place types."""
    import matplotlib.pyplot as plt
    scored = regions[(regions["scored"] == True)].dropna(subset=["diversity_score"]).set_index("sa2_code")
    density = (scored["intensity_score"] + scored["design_score"]) / 2
    x_low, x_high = padded_score_range(density)
    y_low, y_high = 60, SCORE_AXIS_HIGH
    fig, axis = plt.subplots(figsize=(8.5, 6.4), dpi=180)
    axis.axvline(100, color=GUIDE_COLOR, linewidth=1, linestyle="--")
    axis.axhline(100, color=GUIDE_COLOR, linewidth=1, linestyle="--")
    corners = [
        ("dense and diverse", 0.99, 0.98, "right", "top"), ("less dense and diverse", 0.01, 0.98, "left", "top"),
        ("less dense and less diverse", 0.01, 0.02, "left", "bottom"),
        ("dense and less diverse", 0.99, 0.02, "right", "bottom"),
    ]
    for place_type, x, y, horizontal, vertical in corners:
        color = COLOR_ROLES["light"][f"place-{PLACE_CSS_NAME[place_type]}-text"]
        axis.text(x, y, place_type, transform=axis.transAxes, ha=horizontal, va=vertical, fontsize=9, color=color)
    named = scatter_dots(axis, density, scored["diversity_score"], scored, y_low, y_high)
    axis.set_xlim(x_low, x_high)
    axis.set_ylim(y_low, y_high)
    axis.set_xlabel("Density score (mean of the Intensity and Design scores)")
    axis.set_ylabel("Diversity score")
    axis.set_title("Density against Diversity", loc="left", fontsize=12, fontweight="bold")
    chart_axes(axis, vertical_grid=True)
    correlation = stats["chart"]["correlations"]["density_diversity"]
    note = f"Dots take the colour of their quintile; the four example places and the top three of each quintile are named. Spearman correlation: {correlation:.2f} (1 would mean the two rank the SA2s in exactly the same order)."
    off_axis = scored[scored["diversity_score"] < y_low]
    if len(off_axis):
        note += f" {sa2_count(len(off_axis))} below the axis: " + join_names(off_axis["sa2_name"].tolist()) + "."
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    add_note(fig, note)
    label_dots(fig, axis, named)
    return save_figure(fig, out_dir, "vibrancy_density_diversity.png")


def figure_example_places(stats, out_dir):
    """Save the four example places: each pillar score as a marker on a 70 to 130 track, then the card's facts."""
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.6), dpi=180)
    for axis, card in zip(axes.flatten(), stats["cards"]):
        axis.set_xlim(SCORE_AXIS_LOW - 22, SCORE_AXIS_HIGH + 22)
        axis.set_ylim(-5.0, 3.6)
        hide_axes(axis)
        axis.set_title(f'{card["name"]}\n{card["place_type"]}', loc="left", fontsize=11, fontweight="bold")
        for row, pillar in enumerate(card["pillars"]):
            y = 2.4 - row * 1.3
            axis.plot([SCORE_AXIS_LOW, SCORE_AXIS_HIGH], [y, y], color="#e1e0d9", linewidth=7, solid_capstyle="round")
            axis.plot([100, 100], [y - 0.45, y + 0.45], color="#52514e", linewidth=1)
            axis.text(SCORE_AXIS_LOW - 3, y, pillar["label"], ha="right", va="center", fontsize=9)
            if pd.isna(pillar["value"]):
                axis.text(100, y, "n/a", ha="center", va="center", fontsize=9, color="#52514e")
                continue
            color = COLOR_ROLES["light"][f"{PILLAR_CSS_NAME[pillar['label']]}-bar"]
            axis.scatter([pillar["clipped"]], [y], s=90, color=color, zorder=3)
            off_scale = pillar["value"] < SCORE_AXIS_LOW or pillar["value"] > SCORE_AXIS_HIGH
            text = f'{pillar["value"]:.1f}' + (" (off scale)" if off_scale else "")
            axis.text(SCORE_AXIS_HIGH + 3, y, text, ha="left", va="center", fontsize=9)
        axis.text(SCORE_AXIS_LOW, -1.1, "70", ha="center", va="top", fontsize=8, color="#52514e")
        axis.text(100, -1.1, "Greater Sydney average", ha="center", va="top", fontsize=8, color="#52514e")
        axis.text(SCORE_AXIS_HIGH, -1.1, "130", ha="center", va="top", fontsize=8, color="#52514e")
        summary = (f'Score {card["score"]:.1f}, rank {card["rank"]} of 372 (1 is the highest). '
                   f'Across the 22 alternative versions its rank runs from {card["rank_min"]} to {card["rank_max"]}.')
        axis.text(SCORE_AXIS_LOW - 22, -2.0, textwrap.fill(summary, 62), ha="left", va="top", fontsize=8.5)
        facts = "\n".join(f'{fact["display"]}, {fact["percentile"]}' for fact in card["facts"])
        axis.text(SCORE_AXIS_LOW - 22, -3.3, facts, ha="left", va="top", fontsize=8.5)
    fig.suptitle("Four places show what the score does and does not capture", x=0.01, ha="left", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    add_note(fig, "Each marker is a pillar score on a fixed axis from 70 to 130 around the Greater Sydney average of 100. The facts are raw counts for each square kilometre, compared with the other scored SA2s.")
    return save_figure(fig, out_dir, "vibrancy_example_places.png")


def figure_walking_counts(regions, stats, day, out_dir):
    """Save one day's walking-count scatterplot: score across, average daily count up, the three busiest sites named."""
    import matplotlib.pyplot as plt
    sites = stats["chart"]["foot_sites"].dropna(subset=[f"{day}_average"])
    ranked = regions.set_index("sa2_code")["rank_class"]
    x_low, x_high = padded_score_range(sites["vibrancy_score"])
    top = math.ceil(sites[f"{day}_average"].max() / 10000) * 10000
    fig, axis = plt.subplots(figsize=(8.5, 5.6), dpi=180)
    busiest = set(sites.nlargest(3, f"{day}_average")["sa2_code"])
    named = []
    for _, site in sites.iterrows():
        x, y = site["vibrancy_score"], site[f"{day}_average"]
        axis.scatter([x], [y], s=DOT_SIZE * 3.5, color=RAMP[int(ranked[int(site["sa2_code"])])], linewidths=0)
        if site["sa2_code"] in busiest:
            named.append((x, y, site["sa2_name"]))
    axis.set_xlim(x_low, x_high)
    axis.set_ylim(0, top)
    axis.set_yticks(range(0, top + 1, 10000), [f"{value:,}" for value in range(0, top + 1, 10000)])
    axis.set_xlabel("Vibrancy score")
    axis.set_ylabel(f"Daily count, {day}s")
    axis.set_title(textwrap.fill(stats["foot_titles"][day], 70), loc="left", fontsize=12, fontweight="bold")
    chart_axes(axis, vertical_grid=True)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    add_note(fig, f"Each dot is one SA2 (n = {len(sites)}), all inner-city and all in the top quintile. Counts are City of Sydney pedestrian counts averaged over the four most recent surveys.")
    label_dots(fig, axis, named)
    return save_figure(fig, out_dir, f"vibrancy_walking_{day}.png")


def figure_squares(total, highlighted, caption, note, filename, out_dir):
    """Save a grid of `total` squares in rank order, row by row, with the squares at the `highlighted` positions marked."""
    import matplotlib.pyplot as plt
    positions = np.arange(total)
    across = positions % GRID_COLUMNS
    down = -(positions // GRID_COLUMNS)
    marked = np.array([position in highlighted for position in positions])
    fig, axis = plt.subplots(figsize=(9, 4.6), dpi=180)
    axis.scatter(across[~marked], down[~marked], marker="s", s=170, color=GUIDE_COLOR, linewidths=0)
    axis.scatter(across[marked], down[marked], marker="s", s=170, color=RAMP[-1], linewidths=0)
    axis.set_aspect("equal")
    hide_axes(axis)
    axis.set_title(textwrap.fill(caption, 80), loc="left", fontsize=11, fontweight="bold")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    add_note(fig, note)
    return save_figure(fig, out_dir, filename)


def figure_walking_squares(regions, stats, out_dir):
    """Save the picture of where the SA2s with walking counts sit in the ranking."""
    total = int((regions["scored"] == True).sum())
    foot_sites = stats["chart"]["foot_sites"]
    _, caption = walking_count_squares(total, foot_sites)
    note = "Each square is one scored SA2 in rank order: rank 1 is the top left square. The dark squares have walking counts."
    return figure_squares(total, walking_count_positions(foot_sites), caption, note, "vibrancy_walking_coverage.png", out_dir)


def figure_chance_squares(regions, out_dir):
    """Save the picture of how many of the cluster tests could look special by chance alone."""
    total = int((regions["scored"] == True).sum())
    _, caption, _ = chance_squares(total)
    note = "Each square stands for one test. The dark squares are placed at random and are not real SA2s."
    return figure_squares(total, chance_positions(total), caption, note, "vibrancy_chance.png", out_dir)


def figure_data_map(regions, tables_dir, out_dir):
    """Save a static version of the page's data map: one panel for each dataset, in the page's colours.

    A point panel shows the items that were counted; a school panel shows that group's catchment outlines.
    """
    import matplotlib.pyplot as plt
    columns = 4
    rows = math.ceil(len(DATA_MAP_LAYERS) / columns)
    projected = regions.to_crs(METRIC_CRS)
    frame = built_up_frame()
    layer_dir = Path(tables_dir) / "map_layers"
    catchments = gpd.read_file(layer_dir / "school_catchments.geojson").to_crs(METRIC_CRS)
    fig, axes = plt.subplots(rows, columns, figsize=(14, 3.7 * rows), dpi=180)
    for axis, layer in zip(axes.flat, DATA_MAP_LAYERS):
        colour = COLOR_ROLES["light"][f"data-{layer['key']}"]
        projected.plot(ax=axis, color="#e9e9e5", edgecolor="#b6b7b0", linewidth=0.2)
        if layer["kind"] == "points":
            table = read_table(layer_dir, f"{layer['key']}.csv")
            counted = table[table["inside"]]
            dots = gpd.GeoSeries(gpd.points_from_xy(counted["lon"], counted["lat"]), crs=4326).to_crs(METRIC_CRS)
            axis.scatter(dots.x, dots.y, s=layer["radius"] ** 2 * 0.6, color=colour, linewidths=0, alpha=0.8)
            subtitle = f"{len(counted):,} counted"
        else:
            group = catchments[catchments["school_group"] == layer["group"]]
            group.boundary.plot(ax=axis, color=colour, linewidth=0.5)
            subtitle = f"{len(group):,} touch Greater Sydney"
        axis.set_xlim(min(x for x, y in frame), max(x for x, y in frame))
        axis.set_ylim(min(y for x, y in frame), max(y for x, y in frame))
        axis.set_title(f"{layer['name']}\n{subtitle}", loc="left", fontsize=10, fontweight="bold")
        hide_axes(axis)
    for axis in list(axes.flat)[len(DATA_MAP_LAYERS):]:
        axis.set_visible(False)
    fig.suptitle("Every dataset behind the score, after it was matched to SA2s", x=0.01, ha="left", fontsize=14, fontweight="bold")
    note = ("Dots are the items counted in the SA2 that holds them. Outlines are school catchments, which overlap each other, "
            "so each group has its own panel. Items outside the 373 SA2s are not counted and not shown.")
    fig.text(0.01, 0.005, textwrap.fill(note, 150), fontsize=8, color="#52514e", va="bottom")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95), h_pad=3)
    return save_figure(fig, out_dir, "vibrancy_data_map.png")


def build_chart_figures(regions, stats, out_dir):
    """Save a static version of each chart on the page into `out_dir`/images, and return the saved paths."""
    image_dir = Path(out_dir) / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    return [
        figure_distance(regions, stats, out_dir),
        figure_histogram(regions, stats, out_dir),
        figure_moran(regions, stats, out_dir),
        figure_intensity_design(regions, stats, out_dir),
        figure_density_diversity(regions, stats, out_dir),
        figure_example_places(stats, out_dir),
        figure_walking_counts(regions, stats, "weekday", out_dir),
        figure_walking_counts(regions, stats, "weekend", out_dir),
        figure_walking_squares(regions, stats, out_dir),
        figure_chance_squares(regions, out_dir),
    ]


def float_or_none(value, digits=None):
    """Return a value as a float, rounded to `digits` decimals if given, or None if it is missing."""
    if pd.isna(value):
        return None
    if digits is None:
        return float(value)
    return round(float(value), digits)


def int_or_none(value):
    """Return a value as a whole number, or None if it is missing."""
    if pd.isna(value):
        return None
    return int(value)


def map_counts(row):
    """Return the totals the data map shows when you hover over an SA2 (stops and intersections are set elsewhere)."""
    counts = {}
    for layer in DATA_MAP_LAYERS:
        key = layer["key"]
        if key in ("stops", "intersections"):
            continue
        if layer["kind"] == "areas":
            # A catchment that spans SA2s is shared out by area, so an SA2's total can be a fraction.
            counts[key] = float_or_none(row[key], digits=1)
        else:
            counts[key] = total_count(row[layer["count_column"]], row["area_km2"])
    return counts


def geojson(regions):
    """Return simplified GeoJSON properties needed by the interactive map."""
    data = regions.to_crs(4326).copy()
    data["geometry"] = data.geometry.simplify(0.00035, preserve_topology=True)
    features = []
    for _, row in data.iterrows():
        is_scored = bool(row["scored"]) if pd.notna(row["scored"]) else False
        name = row["sa2_name"] if pd.notna(row["sa2_name"]) else row["SA2_NAME21"]
        if pd.isna(row["intensity_score"]) or pd.isna(row["design_score"]):
            density = None
        else:
            density = round(float((row["intensity_score"] + row["design_score"]) / 2), 1)
        properties = {"id": int(row["sa2_code"]), "name": name, "scored": is_scored,
                      "score": float_or_none(row["vibrancy_score"]),
                      "rank": int_or_none(row["vibrancy_rank"]),
                      "rank_class": int_or_none(row["rank_class"]),
                      "rank_min": int_or_none(row["rank_min"]),
                      "rank_max": int_or_none(row["rank_max"]),
                      "place_type": "not scored" if not is_scored else row["place_type"],
                      "hotspot": "not significant" if not is_scored else row["hotspot_class"],
                      "intensity": float_or_none(row["intensity_score"]),
                      "diversity": float_or_none(row["diversity_score"]),
                      "design": float_or_none(row["design_score"]),
                      "density": density,
                      "intensity_z": float_or_none(row["intensity_z"]),
                      "diversity_z": float_or_none(row["diversity_z"]),
                      "design_z": float_or_none(row["design_z"]),
                      "distance_km": float_or_none(row["distance_km"]),
                      "residents": int_or_none(row["residents"]),
                      "median_income": int_or_none(row["median_income"]),
                      "businesses": total_count(row["businesses_per_km2"], row["area_km2"]),
                      "stops": total_count(row["stops_per_km2"], row["area_km2"]),
                      "intersections": total_count(row["intersections_per_km2"], row["area_km2"]),
                      "neighbour_average_score": float_or_none(row["neighbour_average_score"], digits=1),
                      "hotspot_p_value": float_or_none(row["hotspot_p_value"], digits=3),
                      "residents_per_ha": float_or_none(row["residents_per_ha"]),
                      "businesses_per_km2": float_or_none(row["businesses_per_km2"]),
                      "stops_per_km2": float_or_none(row["stops_per_km2"]),
                      "intersections_per_km2": float_or_none(row["intersections_per_km2"]),
                      "flag": "" if pd.isna(row["flag"]) else str(row["flag"])}
        properties.update(map_counts(row))
        geometry = json.loads(gpd.GeoSeries([row.geometry], crs=4326).to_json())["features"][0]["geometry"]
        features.append({"type": "Feature", "properties": properties, "geometry": geometry})
    return {"type": "FeatureCollection", "features": features}


def table_records(table):
    """Return a table's rows as a list of dicts, with missing values as None (null in the page's JSON)."""
    return table.where(pd.notna(table), None).to_dict("records")


def flat_coordinates(table):
    """Return a points table as one flat list: longitude, latitude, longitude, latitude, and so on."""
    pairs = zip(table["lon"].round(MAP_COORDINATE_DIGITS), table["lat"].round(MAP_COORDINATE_DIGITS))
    return [float(value) for pair in pairs for value in pair]


def write_layer_file(path, key, content):
    """Write one layer as a small script that hands its data to the page's mapLayerLoaded function."""
    text = json.dumps(content, separators=(",", ":")).replace("</", "<\\/")
    path.write_text(f'mapLayerLoaded("{key}",{text});\n', encoding="utf-8")


def write_map_layers(regions, tables_dir, out_dir):
    """Write one script per data-map layer, so the page loads a dataset only when it is switched on.

    Each point layer holds the points that were counted, the points that fall outside the 373 SA2s but near
    the map (shown as rings on request) and the number of outside points in all. The school layer holds the
    catchments that touch Greater Sydney, one file for each group (primary, high school and infants).
    """
    layer_dir = Path(out_dir) / "map_layers"
    layer_dir.mkdir(parents=True, exist_ok=True)
    west, south, east, north = regions.to_crs(4326).total_bounds
    for key in MAP_POINT_KEYS:
        points = read_table(Path(tables_dir) / "map_layers", f"{key}.csv")
        outside = points[~points["inside"]]
        near_lon = outside["lon"].between(west - MAP_EDGE_MARGIN, east + MAP_EDGE_MARGIN)
        near_lat = outside["lat"].between(south - MAP_EDGE_MARGIN, north + MAP_EDGE_MARGIN)
        near_edge = near_lon & near_lat
        write_layer_file(layer_dir / f"{key}.js", key, {
            "counted": flat_coordinates(points[points["inside"]]),
            "outside": flat_coordinates(outside[near_edge]),
            "outside_total": len(outside),
        })
    catchments = gpd.read_file(Path(tables_dir) / "map_layers" / "school_catchments.geojson")
    catchments.geometry = catchments.geometry.simplify(SCHOOL_SIMPLIFY_TOLERANCE)
    catchments.geometry = shapely.set_precision(catchments.geometry.values, SCHOOL_GRID_SIZE)
    for layer in DATA_MAP_LAYERS:
        if layer["kind"] == "areas":
            group = catchments[catchments["school_group"] == layer["group"]][["geometry"]]
            write_layer_file(layer_dir / f"{layer['key']}.js", layer["key"], json.loads(group.to_json(drop_id=True)))


def data_map_chips():
    """Return the buttons that switch each dataset on the data map."""
    buttons = ""
    for layer in DATA_MAP_LAYERS:
        buttons += (
            f'<button class="chip data-layer" data-key="{layer["key"]}" aria-pressed="false">'
            f'<i class="data-dot" style="background:var(--data-{layer["key"]})"></i>{html.escape(layer["name"])}</button>'
        )
    return buttons


def page_html(regions, stats):
    """Fill the template with page statistics, cards and map data."""
    headline = stats["headline"]
    cards = "".join(card_html(card) for card in stats["cards"])
    type_rows = ""
    for _, row in stats["place_types"].iterrows():
        name = html.escape(str(row.place_type))
        css_name = place_css_class(row.place_type)
        type_rows += (
            f'<tr class="type-row type-{css_name}" data-place-type="{name}"><td>'
            f'<span class="type-name"><i class="type-swatch"></i>{name}</span></td><td>{int(row.sa2s)}</td>'
            f'<td>{int(row.residents):,}</td><td>'
            f'{html.escape(str(row.best_ranked_examples))}</td></tr>'
        )
    chart = stats["chart"]
    data = {"geo": geojson(regions), "ramp": RAMP, "hotspot_styles": HOTSPOT_STYLES,
            "place_colors": PLACE_COLORS, "hotspot_order": HOTSPOT_ORDER, "global_i": stats["global_i"],
            "layers": stats["layers"], "built_up_bounds": stats["built_up_bounds"],
            "equity": stats["equity"].to_dict("records"), "rank_bands": stats["rank_bands"],
            "foot_sites": table_records(chart["foot_sites"]),
            "correlations": chart["correlations"],
            "variant_ranks": table_records(chart["variant_ranks"]),
            "sensitivity": table_records(chart["sensitivity"]),
            "score_middle_share": stats["score_middle_share"],
            "card_names": [card["name"] for card in stats["cards"]], "data_layers": DATA_MAP_LAYERS}
    limits = "".join(f"<li>{html.escape(item)}</li>" for item in stats["limits"])
    scored_sa2s = headline["scored_sa2s"]
    coverage_picture, coverage_caption = walking_count_squares(scored_sa2s, chart["foot_sites"])
    chance_picture, chance_caption, by_chance = chance_squares(scored_sa2s)
    scored_regions = regions[regions["scored"] == True]
    labelled_clusters = int((scored_regions["hotspot_class"] != "not significant").sum())
    replacements = {
        "TITLE": stats["headline_title"],
        "TOP_AREA": f"{headline['top_area_share']:.1%}", "TOP_RESIDENTS": f"{headline['top_resident_share']:.1%}",
        "SCORED_SA2S": str(headline["scored_sa2s"]),
        "EQUITY_HIGH": f"{stats['equity_high']:.1f}%", "EQUITY_LOW": f"{stats['equity_low']:.1f}%",
        "EQUITY_TITLE": stats["equity_title"],
        "DENSE_DIVERSE_COUNT": str(stats["dense_diverse_count"]),
        "DENSE_LESS_COUNT": str(stats["dense_less_count"]),
        "WEEKDAY_CORRELATION": f"{foot_traffic_spearman(stats['foot'], 'weekday'):.2f}",
        "WEEKEND_CORRELATION": f"{foot_traffic_spearman(stats['foot'], 'weekend'):.2f}",
        "TOP_OVERLAP": f"{stats['top_overlap_min']} to {stats['top_overlap_max']}", "GLOBAL_I": f"{stats['global_i']:.2f}",
        "GLOBAL_P": f"{stats['global_p']:.3f}", "MEDIAN_RANGE": f"{stats['median_rank_range']:.0f}",
        "SCORE_MIDDLE_SHARE": f"{stats['score_middle_share']:.0%}", "TOTAL_SA2S": str(stats["total_sa2s"]),
        "MAP_CAPTION": (
            f"The {stats['map_caption']['top_count']} SA2s in the darkest blue take up about "
            f"{stats['map_caption']['area_share']:.1%} of the area we scored and hold "
            f"{stats['map_caption']['resident_share']:.1%} of residents. Beyond 10 km from "
            f"the CBD, {stats['map_caption']['outer_count']} SA2s are in the darkest blue, "
            f"including {stats['map_caption']['outer_names']}."
        ),
        "STABILITY_NOTICE": (
            "Ranks near the top and the bottom of the table hold still; ranks in the middle "
            "move the most."
        ),
        "DISTANCE_TITLE": html.escape(stats["distance"]["title"]),
        "HISTOGRAM_TITLE": html.escape(stats["histogram"]["title"]),
        "MORAN_TITLE": html.escape(stats["moran"]["title"]),
        "MORAN_TEXT": "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in stats["moran"]["paragraphs"]),
        "CARDS": cards,
        "TYPE_ROWS": type_rows,
        "LIMITS": limits,
        "COVERAGE_PICTURE": coverage_picture, "COVERAGE_CAPTION": html.escape(coverage_caption),
        "CHANCE_PICTURE": chance_picture, "CHANCE_CAPTION": html.escape(chance_caption),
        "BY_CHANCE": str(by_chance),
        "LABELLED_CLUSTERS": str(labelled_clusters),
        "METHODS_DETAIL": pillar_html(METHODS_DETAIL),
        "DATA_MAP_CHIPS": data_map_chips(),
        "COLOR_VARIABLES_LIGHT": css_color_variables("light"),
        "COLOR_VARIABLES_DARK": css_color_variables("dark"),
        "DATA": json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/"),
    }
    page = TEMPLATE.read_text(encoding="utf-8")
    for key, value in replacements.items():
        page = page.replace("{{" + key + "}}", value)
    return page


def card_html(card):
    """Return one accessible HTML place card from computed card values."""
    pillars = ""
    for item in card["pillars"]:
        if pd.isna(item["value"]):
            # A missing pillar shows n/a only: an empty track, no marker and no off-scale note.
            bar = '<div class="bar missing" title="Pillar score n/a"></div>'
            marker = "n/a"
            note = ""
        else:
            offset = (item["clipped"] - 100) / 30 * 50
            rounded = round(float(item["value"]), 1)
            marker = "0.0" if rounded == 0 else f"{rounded:.1f}"
            off_scale = item["value"] < 70 or item["value"] > 130
            note = '<small>off scale</small>' if off_scale else ''
            title = marker + (' (off scale)' if off_scale else '')
            bar = f'<div class="bar" style="--offset:{offset:.3f}%" title="Pillar score {title}"><i></i></div>'
        name = PILLAR_CSS_NAME[item["label"]]
        pillars += (
            f'<div class="pillar {name}" data-pillar="{name}"><span>{item["label"]}</span>'
            f'{bar}<b><span>{marker}</span>{note}</b></div>'
        )
    facts = "".join(
        f'<li><strong>{item["display"]}</strong><span>{item["percentile"]}</span></li>'
        for item in card["facts"]
    )
    css_name = place_css_class(card["place_type"])
    return (
        f'<article class="place-card type-{css_name}" data-place-type="{html.escape(card["place_type"])}">'
        f'<p class="kicker type-chip">{html.escape(card["place_type"])}</p>'
        f'<h3>{html.escape(card["name"])}</h3>'
        f'<p class="rank">Score {card["score"]:.1f}, rank {card["rank"]} of 372 (1 is the highest). '
        f'Across the 22 alternative versions of the score its rank runs from {card["rank_min"]} to {card["rank_max"]}.</p>'
        '<div class="axis-labels"><span>70</span><span>Greater Sydney average</span>'
        f'<span>130</span></div><div class="pillars">{pillars}</div>'
        f'<ul class="facts">{facts}</ul><p>{html.escape(card["text"])}</p></article>'
    )


def build(scores=OUTPUT_DIR / "vibrancy_scores.csv", out_dir=ROOT / "vibrancy", tables_dir=OUTPUT_DIR, page=True, images=True):
    """Write the story page and static figures from saved output files."""
    out_dir = Path(out_dir)
    regions = add_school_group_counts(add_hotspot_columns(load_regions(scores), tables_dir), tables_dir)
    stats = compute_stats(regions, tables_dir)
    assert stats["rank_counts"] == [74, 74, 75, 74, 75] or int(regions["scored"].eq(True).sum()) != 372
    written = []
    if images:
        image_dir = out_dir / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        written.append(figure_main_map(regions, stats, out_dir))
        written.extend(figure_pillars(regions, out_dir))
        written.append(figure_place_types(regions, stats, out_dir))
        written.append(figure_equity(stats, out_dir))
        written.append(figure_rank_ranges(stats, out_dir))
    if page:
        out_dir.mkdir(parents=True, exist_ok=True)
        page_path = out_dir / "index.html"
        page_path.write_text(page_html(regions, stats), encoding="utf-8")
        write_map_layers(regions, tables_dir, out_dir)
        written.append(page_path)
    return regions, stats, written


def main():
    """Build the page from command-line paths."""
    import matplotlib
    matplotlib.use("Agg")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", default=str(OUTPUT_DIR / "vibrancy_scores.csv"))
    parser.add_argument("--out", default=str(ROOT / "vibrancy"))
    parser.add_argument("--tables", default=str(OUTPUT_DIR))
    parser.add_argument("--no-page", action="store_true")
    parser.add_argument("--no-images", action="store_true")
    args = parser.parse_args()
    _, _, paths = build(args.scores, args.out, args.tables, not args.no_page, not args.no_images)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
