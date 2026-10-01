#!/usr/bin/env python3
"""Build the Greater Sydney vibrancy story from saved output tables."""

import argparse
import html
import json
import math
import random
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
TEMPLATE = Path(__file__).with_name("vibrancy_story_template.html")
# The colour-roles table: the one place in the code where every named colour is defined, for both themes. Every
# other colour name in this file (RAMP, PLACE_COLORS, HOTSPOT_COLORS, ...) and every colour in the template's CSS
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
    },
}
# Views into the table above, kept so the rest of this file reads as it did before the colour-roles table existed.
RAMP = [COLOR_ROLES["light"][f"fifth-{step}"] for step in range(1, 6)]
HOTSPOT_COLOR = COLOR_ROLES["light"]["not-scored"]
PILLAR_COLORS = {
    theme: {
        label: {
            "ramp": [roles[f"{PILLAR_CSS_NAME[label]}-{step}"] for step in range(1, 6)],
            "text": roles[f"{PILLAR_CSS_NAME[label]}-text"],
            "bar": roles[f"{PILLAR_CSS_NAME[label]}-bar"],
        }
        for label in PILLAR_ORDER
    }
    for theme, roles in COLOR_ROLES.items()
}
PLACE_CSS_NAME = {
    "dense and diverse": "dense-diverse",
    "dense and less diverse": "dense-less-diverse",
    "less dense and diverse": "less-dense-diverse",
    "less dense and less diverse": "less-dense-less-diverse",
}
PLACE_THEME_COLORS = {
    theme: {label: roles[f"place-{PLACE_CSS_NAME[label]}"] for label in PLACE_CSS_NAME}
    for theme, roles in COLOR_ROLES.items()
}
PLACE_COLORS = PLACE_THEME_COLORS["light"]
# The text-safe shade of each place colour (see the COLOR_ROLES comment above), for a place-type name
# written as coloured letters rather than shown as a map fill or a swatch next to plain text.
PLACE_TEXT_THEME_COLORS = {
    theme: {label: roles[f"place-{PLACE_CSS_NAME[label]}-text"] for label in PLACE_CSS_NAME}
    for theme, roles in COLOR_ROLES.items()
}
HOTSPOT_STYLES = {
    "high-high": {"weight": 1.5, "dash": ""},
    "low-low": {"weight": 1.5, "dash": "5 3"},
    "high-low": {"weight": 1.2, "dash": "2 2"},
    "low-high": {"weight": 1.2, "dash": "7 2 2 2"},
}
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
# Local Moran's I clusters: the class order, plain names for the page, and the light-theme colours (the page's CSS holds
# the same light values and a set for the dark theme). No cluster colour is one of the fifths' blues or a place-type colour.
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
HOTSPOT_COLORS = {name: COLOR_ROLES["light"][role] for name, role in HOTSPOT_CSS_NAME.items()}
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
    for label, name in PLACE_CSS_NAME.items():
        variables.append(f"--place-{name}:{PLACE_THEME_COLORS[theme][label]}")
        variables.append(f"--place-{name}-text:{PLACE_TEXT_THEME_COLORS[theme][label]}")
    for name in HOTSPOT_CSS_NAME.values():
        variables.append(f"--{name}:{roles[name]}")
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


def colour_sheet_rows(theme):
    """Return the labelled rows shown on one half of the colour reference sheet."""
    roles = COLOR_ROLES[theme]
    rows = [("Overall", [roles[f"fifth-{step}"] for step in range(1, 6)], ["1", "2", "3", "4", "5"])]
    for label in PILLAR_ORDER:
        name = PILLAR_CSS_NAME[label]
        colours = [roles[f"{name}-{step}"] for step in range(1, 6)]
        colours.extend([roles[f"{name}-text"], roles[f"{name}-bar"]])
        rows.append((label, colours, ["1", "2", "3", "4", "5", "text", "bar"]))
    place_labels = list(PLACE_CSS_NAME)
    rows.append(("Place types", [PLACE_THEME_COLORS[theme][label] for label in place_labels], place_labels))
    rows.append(("Clusters", [roles[HOTSPOT_CSS_NAME[name]] for name in HOTSPOT_ORDER], HOTSPOT_ORDER))
    neutral_names = ["ink", "muted", "cluster-not-significant", "unavailable", "not-scored"]
    neutral_labels = ["Ink", "Muted", "Not a cluster", "Not available", "Not scored"]
    rows.append(("Neutrals", [roles[name] for name in neutral_names], neutral_labels))
    return rows


def figure_colour_system(path):
    """Draw the light and dark colour roles side by side and return the saved path."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(22, 10), dpi=160)
    for axis, theme in zip(axes, ["light", "dark"]):
        surface = "#fcfcfb" if theme == "light" else "#1a1a19"
        ink = COLOR_ROLES[theme]["ink"]
        axis.set_facecolor(surface)
        axis.set_xlim(0, 10.2)
        axis.set_ylim(0, 8.2)
        axis.set_title(theme.title() + " theme", color=ink, loc="left", fontsize=15, fontweight="bold")
        for row_index, (row_label, colours, labels) in enumerate(colour_sheet_rows(theme)):
            y = 6.8 - row_index
            axis.text(0, y + 0.42, row_label, color=ink, fontsize=10, fontweight="bold", va="bottom")
            for colour_index, (colour, label) in enumerate(zip(colours, labels)):
                x = 1.55 + colour_index * 1.18
                face = "none" if label == "Not scored" else colour
                axis.add_patch(Rectangle((x, y), 0.78, 0.68, facecolor=face, edgecolor=colour, linewidth=1.4))
                axis.text(x + 0.39, y - 0.08, colour, color=ink, fontsize=7, ha="center", va="top")
                display_label = label.replace(" and ", "\nand\n").replace("Not ", "Not\n")
                axis.text(x + 0.39, y + 0.34, display_label, color=ink, fontsize=5.5, ha="center", va="center",
                          clip_on=True)
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_visible(False)
    fig.suptitle("Vibrancy colour system", x=0.01, ha="left", fontsize=18, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    assert_figure_text_layout(fig)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path
def rank_class(rank, number_of_sa2s=372):
    """Return a top-to-bottom rank-fifth class index for one rank."""
    if pd.isna(rank):
        return None
    position = int(float(rank)) - 1
    return 4 - int(np.floor(position * 5 / number_of_sa2s))


def read_table(tables_dir, filename, columns):
    """Read one optional output table or return its empty schema."""
    path = Path(tables_dir) / filename
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=columns)


def add_hotspot_columns(regions, tables_dir):
    """Add each SA2's neighbours' average score and local p-value from the saved hot-spot table."""
    columns = ["sa2_code", "p_value", "neighbour_average_score"]
    table = read_table(tables_dir, "vibrancy_hotspots.csv", columns)[columns].copy()
    table["sa2_code"] = table["sa2_code"].astype(int)
    table = table.rename(columns={"p_value": "hotspot_p_value"})
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
        "top_sa2s": len(top),
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
        f"exactly alike; here it is {global_i:.2f}, so nearby SA2s often score alike. This does not tell us why.",
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
                "Its high Intensity and Design bars sit with above-average Diversity, making it a "
                "dense and varied example. The rank range shows that it remains near the top "
                "when the method changes."
            ),
            "Sydney (South) - Haymarket": (
                "It is dense and well connected, and its Diversity bar sits almost exactly on the "
                "Greater Sydney average, just above the line that makes a place count as diverse. A small "
                "change in the data could move it into the dense and less diverse group."
            ),
            "Gosford - Springfield": (
                "It has high Diversity without the same concentration of places as the leading "
                "inner-city SA2s. Its wide rank range makes the type clearer than a precise "
                "middle-table position."
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
    ranks = read_table(tables_dir, "vibrancy_variant_ranks.csv", ["sa2_code", "sa2_name", "Baseline"])
    sensitivity = read_table(tables_dir, "vibrancy_sensitivity.csv", ["variant", "spearman_rank_correlation", "top_25_overlap"])
    foot = read_table(tables_dir, "vibrancy_foot_traffic_sa2.csv", ["sa2_code", "weekday_average", "weekend_average", "sa2_name"])
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


def walking_count_squares(scored_sa2s, foot_sites):
    """Return the picture and its caption for the SA2s that have walking counts, shown among all scored SA2s in rank order."""
    ranks = sorted(int(rank) for rank in foot_sites["vibrancy_rank"].dropna())
    if not ranks:
        return squares_svg(scored_sa2s, set(), "No SA2s have walking counts."), "No SA2s have walking counts."
    highlighted = {rank - 1 for rank in ranks}
    description = (f"{len(ranks)} of {scored_sa2s} scored SA2s have walking counts. "
                   f"All of them are ranked {ranks[0]} to {ranks[-1]}.")
    caption = (f"{len(ranks)} of the {scored_sa2s} scored SA2s have walking counts, and all of them rank "
               f"{ranks[0]} to {ranks[-1]}. The other {scored_sa2s - len(ranks)} could not be checked this way.")
    return squares_svg(scored_sa2s, highlighted, description), caption


def chance_squares(scored_sa2s):
    """Return the picture and its caption for how many tests pass by chance alone, with squares placed at random."""
    by_chance = round(CHANCE_LEVEL * scored_sa2s)
    highlighted = set(random.Random(CHANCE_SEED).sample(range(scored_sa2s), by_chance))
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


def methods_detail():
    """Return the short methods summary that opens the final panel."""
    return (
        "The score combines 14 indicators in three pillars. Intensity is how much is packed into an area "
        "(ten indicators), Diversity is how varied its mix of businesses and land uses is (two), and Design "
        "is how connected its streets are (two). Each indicator is put on a common scale and averaged, and "
        "the three pillars count equally. 22 alternative versions test how much the ranking depends on "
        "these choices."
    )


def compute_stats(regions, tables_dir=OUTPUT_DIR):
    """Collect every page number from saved score and analysis outputs."""
    headline = top_fifth_stats(regions)
    scored = regions[regions["scored"] == True].copy()
    rank_counts = [int((scored["rank_class"] == value).sum()) for value in range(5)]
    layers = layer_definitions(regions)
    equity = read_table(tables_dir, "vibrancy_equity.csv", ["income_group", "top_quintile_share", "bottom_quintile_share"])
    sensitivity = read_table(tables_dir, "vibrancy_sensitivity.csv", ["top_25_overlap"])
    hotspots = read_table(tables_dir, "vibrancy_hotspot_global.csv", ["global_morans_i", "p_value"])
    place_types = read_table(tables_dir, "vibrancy_place_types.csv", ["place_type", "sa2s", "residents"])
    foot = read_table(tables_dir, "vibrancy_foot_traffic_check.csv", ["day_type", "sa2s", "spearman"])
    chart = chart_inputs(regions, tables_dir)
    top_overlap = sensitivity["top_25_overlap"] if "top_25_overlap" in sensitivity else pd.Series(dtype=float)
    stats = {"headline": headline, "rank_counts": rank_counts, "equity": equity, "place_types": place_types,
             "cards": build_cards(regions), "median_rank_range": float((scored["rank_max"] - scored["rank_min"]).median()),
             "top_overlap_min": int(top_overlap.min()) if len(top_overlap) else 0,
             "top_overlap_max": int(top_overlap.max()) if len(top_overlap) else 0,
             "global_i": float(hotspots.iloc[0]["global_morans_i"]) if len(hotspots) else np.nan,
             "global_p": float(hotspots.iloc[0]["p_value"]) if len(hotspots) else np.nan,
             "foot": foot, "score_labels": score_fifth_labels(scored),
             "score_middle_share": float(((scored["vibrancy_score"] >= 90) & (scored["vibrancy_score"] < 110)).mean()),
             "rank_bands": rank_band_summary(scored), "layers": layers,
             "built_up_bounds": START_VIEW, "map_caption": map_caption(regions, headline),
             "chart": chart, "limits": limit_items(scored, chart["foot_sites"]),
             "methods_detail": methods_detail(), "total_sa2s": len(regions)}
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
    """Return one-decimal score-range labels for the five ranking fifths."""
    boundaries = scored["vibrancy_score"].quantile([0.2, 0.4, 0.6, 0.8]).to_list()
    low, middle_low, middle_high, high = boundaries
    return [
        f"Top quintile: {high:.1f} and above",
        f"Second quintile: {middle_high:.1f} to under {high:.1f}",
        f"Middle quintile: {middle_low:.1f} to under {middle_high:.1f}",
        f"Fourth quintile: {low:.1f} to under {middle_low:.1f}",
        f"Bottom quintile: under {low:.1f}",
    ]


def layer_definitions(regions):
    """Return map classes, labels and counts for the five interactive layers."""
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
        low, middle_low, middle_high, high = available.quantile(
            [0.2, 0.4, 0.6, 0.8]
        ).to_list()
        labels = [
            f"Top quintile: {high:.1f} and above",
            f"Second quintile: {middle_high:.1f} to under {high:.1f}",
            f"Middle quintile: {middle_low:.1f} to under {middle_high:.1f}",
            f"Fourth quintile: {low:.1f} to under {middle_low:.1f}",
            f"Bottom quintile: under {low:.1f}",
        ]
        layers[key] = {"name": name, "classes": classes, "labels": labels,
                       "counts": [int((classes == value).sum()) for value in range(4, -1, -1)],
                       "unavailable": int(scored[column].isna().sum())}
    type_counts = scored["place_type"].value_counts()
    layers["place_types"] = {
        "name": "Place types",
        "classes": scored["place_type"],
        "labels": list(PLACE_COLORS),
        "counts": [int(type_counts.get(name, 0)) for name in PLACE_COLORS],
        "unavailable": 0,
    }
    hotspot_counts = scored["hotspot_class"].value_counts()
    layers["hotspots"] = {
        "name": "Hot spots",
        "classes": scored["hotspot_class"],
        "labels": [HOTSPOT_NAMES[name] for name in HOTSPOT_ORDER],
        "counts": [int(hotspot_counts.get(name, 0)) for name in HOTSPOT_ORDER],
        "unavailable": 0,
    }
    return layers


def built_up_bounds(regions):
    """Return bounds for SA2s holding about 95 percent of residents by density."""
    scored = regions[regions["scored"] == True].sort_values("residents_per_ha", ascending=False).copy()
    cumulative = scored["residents"].cumsum() / scored["residents"].sum()
    built = scored.loc[cumulative <= 0.95]
    if built.empty:
        built = scored
    west, south, east, north = built.to_crs(4326).total_bounds
    return [[float(south), float(west)], [float(north), float(east)]]


def map_caption(regions, headline):
    """Return the data-led main-map caption and outer top-fifth examples."""
    top = regions[(regions["scored"] == True) & (regions["vibrancy_quintile"] == 5)]
    outer = top[top["distance_km"] > 10].sort_values("vibrancy_rank")
    names = outer["sa2_name"].head(4).tolist()
    if len(names) > 1:
        outer_names = ", ".join(names[:-1]) + " and " + names[-1]
    else:
        outer_names = ", ".join(names)
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
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_visible(False)
    fig.suptitle(title, x=0.01, ha="left", fontsize=14, fontweight="bold")
    entries = key_entries + (outline_key_entries(drawn) if outlines else [])
    legend = fig.legend(handles=entries, loc="lower center", ncol=2, frameon=False, fontsize=9)
    for label in legend.get_texts():
        if label.get_text() == OUTLINE_KEY_HEADER:
            label.set_fontweight("bold")
    key_rows = (len(entries) + 1) // 2
    fig.tight_layout(rect=(0, 0.03 + 0.028 * key_rows, 1, 0.965))
    assert_figure_text_layout(fig)
    path = Path(out_dir) / "images" / filename
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


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
    axis.set_xticks([])
    axis.set_yticks([])
    for spine in axis.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    assert_figure_text_layout(fig)
    path = Path(out_dir) / "images" / filename
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


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
        paths.append(save_map(copy, "rank_class", filename, f"{label} by rank quintile", out_dir, key_entries,
                              note=f"Darker = higher quintile of {label}", ramp=PILLAR_COLORS["light"][label]["ramp"]))
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
    assert_figure_text_layout(fig)
    path = Path(out_dir) / "images" / "vibrancy_equity.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


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
    assert_figure_text_layout(fig)
    path = Path(out_dir) / "images" / "vibrancy_rank_ranges.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def geojson(regions):
    """Return simplified GeoJSON properties needed by the interactive map."""
    data = regions.to_crs(4326).copy()
    data["geometry"] = data.geometry.simplify(0.00035, preserve_topology=True)
    features = []
    for _, row in data.iterrows():
        is_scored = bool(row["scored"]) if pd.notna(row["scored"]) else False
        name = row["sa2_name"] if pd.notna(row["sa2_name"]) else row["SA2_NAME21"]
        properties = {"id": int(row["sa2_code"]), "name": name, "scored": is_scored,
                      "score": None if pd.isna(row["vibrancy_score"]) else float(row["vibrancy_score"]),
                      "rank": None if pd.isna(row["vibrancy_rank"]) else int(row["vibrancy_rank"]),
                      "rank_class": None if pd.isna(row["rank_class"]) else int(row["rank_class"]),
                      "rank_min": None if pd.isna(row["rank_min"]) else int(row["rank_min"]),
                      "rank_max": None if pd.isna(row["rank_max"]) else int(row["rank_max"]),
                      "place_type": "not scored" if not is_scored else row["place_type"],
                      "hotspot": "not significant" if not is_scored else row["hotspot_class"],
                      "intensity": None if pd.isna(row["intensity_score"]) else float(row["intensity_score"]),
                      "diversity": None if pd.isna(row["diversity_score"]) else float(row["diversity_score"]),
                      "design": None if pd.isna(row["design_score"]) else float(row["design_score"]),
                      "density": (
                          None
                          if pd.isna(row["intensity_score"]) or pd.isna(row["design_score"])
                          else round(
                              float((row["intensity_score"] + row["design_score"]) / 2), 1
                          )
                      ),
                      "intensity_z": None if pd.isna(row["intensity_z"]) else float(row["intensity_z"]),
                      "diversity_z": None if pd.isna(row["diversity_z"]) else float(row["diversity_z"]),
                      "design_z": None if pd.isna(row["design_z"]) else float(row["design_z"]),
                      "distance_km": None if pd.isna(row["distance_km"]) else float(row["distance_km"]),
                      "residents": None if pd.isna(row["residents"]) else int(row["residents"]),
                      "median_income": None if pd.isna(row["median_income"]) else int(row["median_income"]),
                      "businesses": total_count(row["businesses_per_km2"], row["area_km2"]),
                      "stops": total_count(row["stops_per_km2"], row["area_km2"]),
                      "intersections": total_count(row["intersections_per_km2"], row["area_km2"]),
                      "neighbour_average_score": (
                          None if pd.isna(row["neighbour_average_score"]) else round(float(row["neighbour_average_score"]), 1)
                      ),
                      "hotspot_p_value": None if pd.isna(row["hotspot_p_value"]) else round(float(row["hotspot_p_value"]), 3),
                      "residents_per_ha": None if pd.isna(row["residents_per_ha"]) else float(row["residents_per_ha"]),
                      "businesses_per_km2": None if pd.isna(row["businesses_per_km2"]) else float(row["businesses_per_km2"]),
                      "stops_per_km2": None if pd.isna(row["stops_per_km2"]) else float(row["stops_per_km2"]),
                      "intersections_per_km2": None if pd.isna(row["intersections_per_km2"]) else float(row["intersections_per_km2"]),
                      "flag": "" if pd.isna(row["flag"]) else str(row["flag"])}
        geometry = json.loads(gpd.GeoSeries([row.geometry], crs=4326).to_json())["features"][0]["geometry"]
        features.append({"type": "Feature", "properties": properties, "geometry": geometry})
    return {"type": "FeatureCollection", "features": features}


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
    bands = stats["rank_bands"]
    notice = "; ".join(f'{band["label"]}: {band["median"]:g} places' for band in bands)
    layer_rows = {
        key: {
            "name": value["name"],
            "labels": value["labels"],
            "counts": value["counts"],
            "unavailable": value["unavailable"],
        }
        for key, value in stats["layers"].items()
    }
    chart = stats["chart"]
    data = {"geo": geojson(regions), "ramp": RAMP, "hotspot_styles": HOTSPOT_STYLES,
            "place_colors": PLACE_COLORS, "hotspot_order": HOTSPOT_ORDER, "global_i": stats["global_i"],
            "layers": layer_rows, "built_up_bounds": stats["built_up_bounds"],
            "equity": stats["equity"].to_dict("records"), "rank_bands": stats["rank_bands"],
            "foot_sites": chart["foot_sites"].where(pd.notna(chart["foot_sites"]), None).to_dict("records"),
            "correlations": chart["correlations"],
            "variant_ranks": chart["variant_ranks"].where(pd.notna(chart["variant_ranks"]), None).to_dict("records"),
            "sensitivity": chart["sensitivity"].where(pd.notna(chart["sensitivity"]), None).to_dict("records"),
            "score_middle_share": stats["score_middle_share"],
            "card_names": [card["name"] for card in stats["cards"]]}
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
        "METHODS_DETAIL": pillar_html(stats["methods_detail"]),
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
    regions = add_hotspot_columns(load_regions(scores), tables_dir)
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
    paths.append(figure_colour_system(OUTPUT_DIR / "colour_system.png"))
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
