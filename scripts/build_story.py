#!/usr/bin/env python3
"""Turn the bustling scores into a short data story: one web page plus static figures.

    python scripts/build_story.py                     # expected/bustling_scores.csv -> output/
    python scripts/build_story.py --out .             # refresh the committed index.html and images/
    python scripts/build_story.py --scores output/bustling_scores.csv

It needs the scores (a CSV or DataFrame with the columns of the `bustling_scores` table) and the
SA2 boundary shapefile in the project folder. It does not need the database, so the story can be
rebuilt from `expected/bustling_scores.csv` alone. The notebook calls `build()` after scoring.

Writes to <out>/:
    index.html                     the interactive story (Leaflet map, three charts, table view)
    images/score_distribution.png  the same four views as static figures
    images/bustling_map.png
    images/distance_from_cbd.png
    images/score_by_income.png

Design choices, in one place (the reasoning is in .ai/TABLEAU_DASHBOARD_GUIDE.md and the
dataviz rules it was applied with):
  * One hue, light to dark, for magnitude. The old map used a red-to-green scale.
  * Five classes with round breaks, so the colours are spread over where the regions actually
    are (the old equal 0.2 bins put 87% of regions, 314 of 359, into two colours). The top class is
    "0.7 and over", which is the 25 regions the headline talks about.
  * Titles say the finding, not the chart type. Grey and blue only; nothing decorative.
  * The same classes, colours and numbers are used on the map, the histogram and the two strip
    plots (distance and income), so the eye learns the key once.
"""
from __future__ import annotations

import argparse
import functools
import html
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SHAPEFILE = DATA_DIR / "SA2_2021_AUST_GDA2020.shp"
TEMPLATE = Path(__file__).with_name("story_template.html")

# --- The parts of the design that every view shares ---------------------------------------------
BREAKS = [0.4, 0.5, 0.6, 0.7]
CLASS_LABELS = ["Under 0.4", "0.4 to 0.5", "0.5 to 0.6", "0.6 to 0.7", "0.7 and over"]
# Ordered blue ramp (palette steps 250/350/450/550/700), so the lightest class still clears 2:1
# against the surface and no two neighbours are closer than 0.06 in lightness. Checked with the
# dataviz validator: validate_palette.py "<hexes>" --ordinal --mode light. The same ordered ramp
# is used in both themes so larger values always have a darker colour. Static figures are light only.
RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"]
RAMP_DARK = RAMP
INK = {"ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
       "grid": "#e1e0d9", "axis": "#c3c2b7", "surface": "#fcfcfb"}

GPO = (151.2073, -33.8678)  # Sydney GPO, Martin Place (lon, lat): the CBD reference point
MGA56 = 7856                # metres, for distances
BANDS = [(0, 5, "Within 5 km"), (5, 10, "5 to 10 km"), (10, 20, "10 to 20 km"),
         (20, 40, "20 to 40 km"), (40, None, "Over 40 km")]
BAND_SHORT = ["0 to 5", "5 to 10", "10 to 20", "20 to 40", "40+"]
# Five equal-sized groups by median income, the same split as scripts/income_correlation.py
INCOME_GROUPS = ["Lowest 20%", "Lower middle", "Middle", "Upper middle", "Highest 20%"]
INCOME_SHORT = ["Lowest", "Lower", "Middle", "Upper", "Highest"]
PLACES = {"Sydney CBD": (-33.8678, 151.2073), "Parramatta": (-33.8150, 151.0011),
          "Hurstville": (-33.9670, 151.1020)}  # (lat, lon), the labels on the map
SIMPLIFY_DEG = 0.0003       # about 30 m; keeps the page small without visibly changing shapes


def classify(score):
    """Class index 0..5 for a score (NaN stays NaN)."""
    s = np.asarray(score, dtype=float)
    return np.where(np.isnan(s), np.nan, np.searchsorted(BREAKS, s, side="right"))


# --- Data ---------------------------------------------------------------------------------------
def load_regions(scores) -> gpd.GeoDataFrame:
    """All 373 Greater Sydney regions, with the score (NaN if not scored), rank, distance and income group."""
    scores = pd.read_csv(scores) if isinstance(scores, (str, Path)) else pd.DataFrame(scores)
    scores = scores.drop(columns=["geom"], errors="ignore")

    bounds = gpd.read_file(SHAPEFILE, engine="pyogrio")
    bounds = bounds[bounds["GCC_NAME21"] == "Greater Sydney"].copy()
    bounds["SA2_CODE21"] = bounds["SA2_CODE21"].astype(int)
    keep = ["SA2_CODE21", "SA2_NAME21", "AREASQKM21", "geometry"]
    g = bounds[keep].merge(
        scores[["SA2_CODE21", "bustling_score", "total_people", "median_income"]],
        on="SA2_CODE21", how="left")

    # Residents for every region (the scores file only has the scored ones)
    pop = pd.read_csv(DATA_DIR / "Population.csv", usecols=["sa2_code", "total_people"])
    g = g.merge(pop.rename(columns={"sa2_code": "SA2_CODE21", "total_people": "residents"}),
                on="SA2_CODE21", how="left")

    projected = g.to_crs(MGA56)
    gpo = gpd.GeoSeries(gpd.points_from_xy([GPO[0]], [GPO[1]]), crs=4326).to_crs(MGA56).iloc[0]
    g["km"] = projected.geometry.centroid.distance(gpo) / 1000
    g["cls"] = classify(g["bustling_score"])
    g["igroup"] = pd.qcut(pd.to_numeric(g["median_income"], errors="coerce"), len(INCOME_GROUPS), labels=False)
    g["rank"] = g["bustling_score"].rank(ascending=False, method="min")
    return g.sort_values("bustling_score", ascending=False, na_position="last").reset_index(drop=True)


def band_of(km) -> int:
    for i, (lo, hi, _) in enumerate(BANDS):
        if km >= lo and (hi is None or km < hi):
            return i
    raise ValueError(km)


def income_range(group) -> str:
    """'$36k to $51k' for one entry of stats["income_groups"] (the lowest and highest income in it)."""
    return f"${group['lo'] / 1000:.0f}k to ${group['hi'] / 1000:.0f}k"


def compute_stats(g: gpd.GeoDataFrame) -> dict:
    """Every number the story quotes, so the text can never drift from the data."""
    s = g[g["bustling_score"].notna()].copy()
    s["band"] = s["km"].map(band_of)
    top = s[s["bustling_score"] > 0.7]
    counts = [int((s["cls"] == i).sum()) for i in range(len(CLASS_LABELS))]
    bands = []
    for i, (lo, hi, label) in enumerate(BANDS):
        b = s[s["band"] == i]["bustling_score"]
        bands.append({"label": label, "short": BAND_SHORT[i], "n": int(len(b)),
                      "median": float(b.median()), "max": float(b.max())})
    income_groups = []
    for i, label in enumerate(INCOME_GROUPS):
        b = s[s["igroup"] == i]  # s is sorted by score, so the first row is the group's busiest region
        income_groups.append({"label": label, "short": INCOME_SHORT[i], "n": int(len(b)),
                              "median": float(b["bustling_score"].median()), "mean": float(b["bustling_score"].mean()),
                              "lo": float(b["median_income"].min()), "hi": float(b["median_income"].max()),
                              "top": [b.iloc[0]["SA2_NAME21"], float(b.iloc[0]["bustling_score"])]})
    outliers = s[(s["bustling_score"] > 0.7) & (s["km"] > 10)].sort_values("bustling_score", ascending=False)
    unscored = g[g["bustling_score"].isna()]
    return {
        "n_total": int(len(g)), "n_scored": int(len(s)), "n_unscored": int(len(unscored)),
        "unscored_names": sorted(unscored["SA2_NAME21"]),
        "unscored_max_people": int(unscored["residents"].max()),
        "median": float(s["bustling_score"].median()),
        "q1": float(s["bustling_score"].quantile(0.25)), "q3": float(s["bustling_score"].quantile(0.75)),
        "share_mid": float(s["bustling_score"].between(0.4, 0.6, inclusive="left").mean()),
        "n_top": int(len(top)), "share_top": float(len(top) / len(s)),
        "top_area_share": float(top["AREASQKM21"].sum() / s["AREASQKM21"].sum()),
        "top_people_share": float(top["total_people"].sum() / s["total_people"].sum()),
        "top_within_15km": int((top["km"] <= 15).sum()),
        "class_counts": counts, "bands": bands, "income_groups": income_groups,
        "top5": s.head(5)[["SA2_NAME21", "bustling_score"]].values.tolist(),
        "outliers": outliers[["SA2_NAME21", "bustling_score", "km"]].values.tolist(),
        "n_outliers": int(len(outliers)),
        "corr_income": float(s["bustling_score"].corr(s["median_income"])),
        "lowest_income": [s.loc[s["median_income"].idxmin(), "SA2_NAME21"],
                          float(s["median_income"].min()),
                          int(s.loc[s["median_income"].idxmin(), "rank"])],
    }


# --- Static figures (and inline in the notebook) ----------------------------------------
RC = {"font.family": "sans-serif", "font.size": 9, "text.color": INK["ink"],
      "axes.edgecolor": INK["axis"], "figure.facecolor": INK["surface"], "axes.facecolor": INK["surface"]}


def _plt():
    import matplotlib.pyplot as plt
    return plt


def _styled(make):
    """Apply the figure style while one figure is drawn, then put those settings back.

    Not plt.rc_context: that restores every rcParam, including `interactive`, which the notebook's
    inline backend switches on when the first figure is created. Restoring it hides every later
    figure, so only the keys in RC are saved and restored here.
    """
    @functools.wraps(make)
    def wrapper(*args, **kwargs):
        import matplotlib
        saved = {key: matplotlib.rcParams[key] for key in RC}
        matplotlib.rcParams.update(RC)
        try:
            return make(*args, **kwargs)
        finally:
            matplotlib.rcParams.update(saved)
    return wrapper


def _headline(fig, title, subtitle):
    fig.text(0.04, 0.955, title, fontsize=15, fontweight="bold", va="top", ha="left")
    fig.text(0.04, 0.895, subtitle, fontsize=10, color=INK["ink2"], va="top", ha="left")


def _class_legend(fig, counts, anchor, ncol=5):
    from matplotlib.patches import Patch
    handles = [Patch(facecolor=RAMP[i], edgecolor="none", label=f"{CLASS_LABELS[i]}  ({counts[i]})")
               for i in range(len(RAMP))]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=anchor, ncol=ncol, frameon=False,
               handlelength=1.0, handleheight=1.0, handletextpad=0.5, columnspacing=1.6,
               borderpad=0, fontsize=8.5, labelcolor=INK["ink2"])


def _quiet_axes(ax, grid_axis="y"):
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(INK["axis"])
    ax.tick_params(colors=INK["ink2"], length=0, labelsize=9)
    ax.grid(axis=grid_axis, color=INK["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def _halo(text_artist):
    import matplotlib.patheffects as pe
    text_artist.set_path_effects([pe.withStroke(linewidth=2.5, foreground=INK["surface"])])


@_styled
def figure_distribution(g, stats):
    """Histogram of the scores, coloured by the map's classes, with the story written on it."""
    plt = _plt()
    s = g["bustling_score"].dropna()
    edges = np.round(np.arange(0.32, 1.0001, 0.02), 2)
    counts, _ = np.histogram(s, bins=edges)
    colors = [RAMP[int(classify(e + 1e-9))] for e in edges[:-1]]

    fig = plt.figure(figsize=(9.6, 5.4), dpi=200)
    _headline(fig, f"{stats['share_mid']:.0%} of regions score between 0.4 and 0.6. "
                   f"Only {stats['share_top']:.0%} pass 0.7.",
              "Each bar counts the regions in one 0.02-wide slice of score, so taller means more regions. Colours match the map.")
    _class_legend(fig, stats["class_counts"], (0.04, 0.855))
    ax = fig.add_axes([0.075, 0.11, 0.90, 0.63])
    ymax = int(np.ceil((counts.max() + 12) / 10) * 10)
    ax.bar(edges[:-1], counts, width=0.02, align="edge", color=colors, edgecolor=INK["surface"],
           linewidth=1.2, zorder=2)
    ax.set_xlim(0.30, 1.01)
    ax.set_ylim(0, ymax)
    ax.set_xticks(np.arange(0.3, 1.01, 0.1))
    ax.set_xticklabels([f"{t:.1f}" for t in np.arange(0.3, 1.01, 0.1)])
    ax.set_yticks(np.arange(0, ymax + 1, 10))
    _quiet_axes(ax)

    # The middle: bracket over 0.4 to 0.6
    yb = counts.max() + 3
    ax.plot([0.4, 0.4, 0.6, 0.6], [yb - 1.2, yb, yb, yb - 1.2], color=INK["ink2"], lw=0.9)
    ax.text(stats["median"] + 0.012, yb + 1.2, f"{stats['share_mid']:.0%} of regions", ha="left",
            va="bottom", fontsize=9.5, fontweight="bold")
    # The median
    m = stats["median"]
    ax.plot([m, m], [0, ymax - 3.2], color=INK["ink"], lw=1.0, zorder=3)
    ax.text(m - 0.006, ymax - 3.2, f"Median {m:.2f}", ha="right", va="top", fontsize=9.5, fontweight="bold")
    # The tail: bracket over 0.7 and up, with the names
    tail_top = counts[edges[:-1] >= 0.7 - 1e-9].max()
    yt = tail_top + 3
    ax.plot([0.7, 0.7, 1.0, 1.0], [yt - 1.2, yt, yt, yt - 1.2], color=INK["ink2"], lw=0.9)
    first = [n.split(" - ")[-1] for n, _ in stats["top5"]]
    ax.text(0.85, yt + 15.5, f"{stats['n_top']} regions score above 0.7", ha="center", va="top",
            fontsize=9.5, fontweight="bold")
    ax.text(0.85, yt + 12.2,
            f"{stats['top_within_15km']} of them are within 15 km of the CBD.\n"
            f"Top five: {', '.join(first[:2])},\n{', '.join(first[2:4])} and {first[4]}.",
            ha="center", va="top", fontsize=8.6, color=INK["ink2"], linespacing=1.45)
    ax.set_xlabel("Bustling score (0 to 1). Regions are scored relative to each other, so 0.5 means "
                  "about typical for Greater Sydney.", fontsize=8.5, color=INK["ink2"], loc="left", labelpad=8)
    return fig


def _swarm(values_pts, radius):
    """Sideways offsets (points) that keep dots of a given radius from overlapping."""
    order = np.argsort(values_pts)
    placed, dx = [], np.zeros(len(values_pts))
    for i in order:
        k, off = 0, 0.0
        while any(np.hypot(px - off, py - values_pts[i]) < 2 * radius + 0.4 for px, py in placed):
            k += 1
            off = (1 if k % 2 else -1) * np.ceil(k / 2) * radius * 0.9
        dx[i] = off
        placed.append((off, values_pts[i]))
    return dx


def _dot_columns(fig, ax, s, group, medians, ylo, yhi, overall, callouts):
    """One swarm of dots per column (height is the score), a black tick at each column's median.

    `group` is the column of `s` that holds each region's column number, 0 to len(medians) - 1.
    `callouts` maps a region name to (lift, side): how far its label sits above the dot, and which
    side of the dot it is written on (1 for the right, -1 for the left). `overall` is the median of
    every region, drawn as a thin line. Returns each column's centre in figure coordinates, for the
    labels underneath. `ax` needs its x limits set first: (0, len(medians)), or a little wider to leave
    a gutter on the right, where the label for the overall median then goes.
    """
    n = len(medians)
    xmax = ax.get_xlim()[1]
    fig.canvas.draw()
    bbox = ax.get_window_extent()
    pt = 72 / fig.dpi
    w_pts, h_pts = bbox.width * pt, bbox.height * pt
    diameter = 5.6
    centres = []
    for i, med in enumerate(medians):
        b = s[s[group] == i]
        y_pts = (b["bustling_score"].values - ylo) / (yhi - ylo) * h_pts
        dx = _swarm(y_pts, diameter / 2) / (w_pts / xmax)
        dx = dx * min(1.0, 0.47 / max(np.abs(dx).max(), 1e-9))  # squeeze, don't clip, so dots never stack
        ax.scatter(i + 0.5 + dx, b["bustling_score"], s=diameter ** 2, color=[RAMP[int(c)] for c in b["cls"]],
                   edgecolor=INK["surface"], linewidth=0.5, zorder=3)
        ax.plot([i + 0.1, i + 0.9], [med, med], color=INK["ink"], lw=2.0, solid_capstyle="round", zorder=4)
        for name, (lift, side) in callouts.items():
            hit = b[b["SA2_NAME21"] == name]
            if len(hit):
                x, y = i + 0.5 + dx[list(b.index).index(hit.index[0])], float(hit["bustling_score"].iloc[0])
                t = ax.text(x + side * 0.06, y + lift, f"{name}  {y:.2f}", fontsize=8.6, va="center",
                            ha="left" if side > 0 else "right")
                _halo(t)
        centres.append(bbox.x0 / fig.bbox.width + (i + 0.5) / xmax * bbox.width / fig.bbox.width)
    ax.axhline(overall, color=INK["muted"], lw=0.8, zorder=1)
    if xmax > n:
        ax.text(n + 0.05, overall, f"All regions\n{overall:.2f}", ha="left", va="center", fontsize=8.6,
                color=INK["ink2"], linespacing=1.3)
    else:
        ax.text(0.02, overall + 0.008, f"All regions: {overall:.2f}", ha="left", va="bottom",
                fontsize=8.6, color=INK["ink2"])
    return centres


def _column_axes(fig, rect, n, ylo, yhi, gutter=0):
    """Axes for a dot-per-region plot with n columns: a quiet score axis on the left and no x axis."""
    ax = fig.add_axes(rect)
    ax.set_xlim(0, n + gutter)
    ax.set_ylim(ylo, yhi)
    _quiet_axes(ax)
    ax.spines["bottom"].set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(["0.4", "0.6", "0.8", "1.0"])
    return ax


@_styled
def figure_distance(g, stats):
    """Every region as a dot, grouped by distance from the CBD; the tick is each group's median."""
    plt = _plt()
    s = g[g["bustling_score"].notna()].copy()
    s["band"] = s["km"].map(band_of)
    fig = plt.figure(figsize=(9.6, 5.6), dpi=200)
    _headline(fig, "Bustle fades with distance from the CBD, with a few outer exceptions",
              "Each dot is one region. Height is its bustling score, colour matches the map, and sideways spread just keeps dots apart.\n"
              "Regions are grouped by distance from the Sydney GPO. The black tick marks each group's median.")
    ylo, yhi = 0.30, 1.07
    ax = _column_axes(fig, [0.075, 0.20, 0.90, 0.61], len(BANDS), ylo, yhi)
    # Callouts sit above their dot, or below for every second one so neighbours don't overprint
    lab = {stats["top5"][0][0]: (0.035, 1)}
    for k, o in enumerate(stats["outliers"]):
        lab[o[0]] = (0.035 if k % 2 == 0 else -0.035, 1)
    centres = _dot_columns(fig, ax, s, "band", [b["median"] for b in stats["bands"]], ylo, yhi,
                           stats["median"], lab)
    for i, x in enumerate(centres):
        fig.text(x, 0.155, f"{BANDS[i][2]}", ha="center", va="top", fontsize=9, color=INK["ink"])
        fig.text(x, 0.115, f"median {stats['bands'][i]['median']:.2f}", ha="center", va="top", fontsize=9,
                 fontweight="bold")
        fig.text(x, 0.078, f"{stats['bands'][i]['n']} regions", ha="center", va="top", fontsize=8.5,
                 color=INK["ink2"])
    fig.text(0.04, 0.025, "Partly by design: every measure is a density, and density falls away from the centre. "
             "Distance is from each region's centre to the Sydney GPO.", fontsize=8, color=INK["ink2"], va="bottom")
    return fig


@_styled
def figure_income(g, stats):
    """Every region as a dot, grouped by median income; the tick is each group's median score."""
    plt = _plt()
    s = g[g["bustling_score"].notna() & g["igroup"].notna()].copy()
    groups = stats["income_groups"]
    fig = plt.figure(figsize=(9.6, 6.2), dpi=200)
    _headline(fig, "Both ends of the income range score a little higher than the middle",
              "Each dot is one region. Height is its bustling score, colour matches the map, and sideways spread just keeps dots apart.\n"
              "Regions are grouped into fifths by median income. The black tick marks each group's median score.")
    ylo, yhi = 0.30, 1.07  # the same scale as the distance figure, so the two can be compared
    ax = _column_axes(fig, [0.075, 0.25, 0.90, 0.55], len(groups), ylo, yhi, gutter=0.5)
    # The top region at each end, so the reader can see both ends hold busy places
    lab = {groups[0]["top"][0]: (0.035, 1), groups[-1]["top"][0]: (0.035, -1)}
    centres = _dot_columns(fig, ax, s, "igroup", [x["median"] for x in groups], ylo, yhi, stats["median"], lab)
    for x, grp in zip(centres, groups):
        fig.text(x, 0.225, grp["label"], ha="center", va="top", fontsize=9, color=INK["ink"])
        fig.text(x, 0.187, income_range(grp).replace("$", r"\$"), ha="center", va="top", fontsize=8.5, color=INK["ink2"])
        fig.text(x, 0.149, f"median {grp['median']:.2f}", ha="center", va="top", fontsize=9, fontweight="bold")
        fig.text(x, 0.111, f"{grp['n']} regions", ha="center", va="top", fontsize=8.5, color=INK["ink2"])
    fig.text(0.04, 0.02, f"The groups overlap heavily, so income says little about any one region "
             f"(correlation {stats['corr_income']:.2f}).\nWhy both ends score higher hasn't been tested. "
             "One idea: dense, busy areas turn up at both ends of the income range.",
             fontsize=8, color=INK["ink2"], va="bottom")
    return fig


@_styled
def figure_map(g, stats):
    """Greater Sydney with a zoom on the inner city, where the small regions are."""
    from matplotlib.patches import Rectangle
    plt = _plt()
    proj = g.to_crs(MGA56)
    proj["geometry"] = proj.geometry.simplify(40, preserve_topology=True)
    scored, hollow = proj[proj["bustling_score"].notna()], proj[proj["bustling_score"].isna()]
    gpo = gpd.GeoSeries(gpd.points_from_xy([GPO[0]], [GPO[1]]), crs=4326).to_crs(MGA56).iloc[0]

    fig = plt.figure(figsize=(10.4, 7.2), dpi=200)
    _headline(fig, "The busiest regions form one tight cluster around the CBD",
              f"Each shape is a region, and darker blue means a higher bustling score. "
              f"Hollow outlines are the {stats['n_unscored']} regions we don't score.")
    _class_legend(fig, stats["class_counts"], (0.04, 0.855))
    ax_all = fig.add_axes([0.02, 0.06, 0.35, 0.74])
    ax_in = fig.add_axes([0.385, 0.06, 0.595, 0.72])

    def paint(ax, lw):
        hollow.plot(ax=ax, facecolor="none", edgecolor=INK["axis"], linewidth=lw)
        scored.plot(ax=ax, color=[RAMP[int(c)] for c in scored["cls"]], edgecolor=INK["surface"], linewidth=lw)
        ax.set_axis_off()
        ax.set_aspect("equal")

    paint(ax_all, 0.2)
    minx, miny, maxx, maxy = proj.total_bounds
    ax_all.set_xlim(minx - 2000, maxx + 2000)
    ax_all.set_ylim(miny - 2000, maxy + 2000)
    half_w = 9500
    half_h = half_w * (0.72 * 7.2) / (0.595 * 10.4)
    zx, zy = (gpo.x - half_w, gpo.x + half_w), (gpo.y - half_h * 0.62, gpo.y + half_h * 1.38)
    ax_all.add_patch(Rectangle((zx[0], zy[0]), zx[1] - zx[0], zy[1] - zy[0], fill=False,
                               edgecolor=INK["ink"], linewidth=0.9))
    paint(ax_in, 0.45)
    ax_in.set_xlim(*zx)
    ax_in.set_ylim(*zy)
    for ax in (ax_all, ax_in):
        ax.spines[:].set_visible(False)

    # Labels: only the places the story leans on
    par = proj[proj["SA2_NAME21"] == "Parramatta - North"].geometry.representative_point().iloc[0]
    ax_all.plot(par.x, par.y, "o", ms=3.2, color=INK["ink"], mec=INK["surface"], mew=0.6)
    _halo(ax_all.text(par.x - 1800, par.y + 200, "Parramatta", fontsize=8, ha="right", va="center"))
    _halo(ax_all.text((zx[0] + zx[1]) / 2, zy[0] - 900, "Inner city, zoomed", fontsize=8, ha="center", va="top", color=INK["ink2"]))
    _halo(ax_in.text(gpo.x + 350, gpo.y + 550, "Sydney CBD", fontsize=9.5, fontweight="bold", ha="left", va="bottom"))
    # scale bar, 5 km
    x0, y0 = zx[0] + 900, zy[0] + 900
    ax_in.plot([x0, x0 + 5000], [y0, y0], color=INK["ink"], lw=1.6, solid_capstyle="butt")
    _halo(ax_in.text(x0 + 2500, y0 + 250, "5 km", ha="center", va="bottom", fontsize=8.5))
    fig.text(0.04, 0.02, "Every measure is a density (per km²), so small, packed regions score high almost by construction. "
             "Read this as where activity is concentrated, not where most people go.",
             fontsize=8, color=INK["ink2"], va="bottom")
    return fig


# --- Interactive page ---------------------------------------------------------------------------
def _geojson(g: gpd.GeoDataFrame) -> dict:
    """Lean GeoJSON: simplified geometry, 5 decimal places, only the properties the page uses."""
    wgs = g.to_crs(4326).copy()
    wgs["geometry"] = wgs.geometry.simplify(SIMPLIFY_DEG, preserve_topology=True)

    def ring(coords):
        return [[round(x, 5), round(y, 5)] for x, y in coords]

    def coords(geom):
        polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        out = [[ring(p.exterior.coords)] + [ring(r.coords) for r in p.interiors] for p in polys]
        return {"type": "MultiPolygon", "coordinates": out}

    feats = []
    for row in wgs.itertuples():
        scored = pd.notna(row.bustling_score)
        props = {"id": int(row.SA2_CODE21), "name": row.SA2_NAME21, "km": round(float(row.km), 1),
                 "score": round(float(row.bustling_score), 4) if scored else None}
        if scored:
            props.update(rank=int(row.rank), band=band_of(row.km), people=int(row.total_people),
                         income=None if pd.isna(row.median_income) else int(row.median_income),
                         igroup=None if pd.isna(row.igroup) else int(row.igroup))
        feats.append({"type": "Feature", "properties": props, "geometry": coords(row.geometry)})
    return {"type": "FeatureCollection", "features": feats}


def _views(g: gpd.GeoDataFrame) -> dict:
    """Map bounds ([[south, west], [north, east]]) for the zoom buttons, computed from the data."""
    wgs = g.to_crs(4326)
    near = wgs[g["km"] <= 40]
    minx, miny, maxx, maxy = near.total_bounds
    lat, lon = GPO[1], GPO[0]
    dlat, dlon = 1 / 111.0, 1 / (111.0 * np.cos(np.radians(lat)))
    par = wgs[wgs["SA2_NAME21"] == "Parramatta - North"].geometry.representative_point().iloc[0]
    box = lambda la, lo, kn, ks, ke, kw: [[round(la - ks * dlat, 4), round(lo - kw * dlon, 4)],
                                          [round(la + kn * dlat, 4), round(lo + ke * dlon, 4)]]
    return {"metro": [[round(miny - 0.02, 4), round(minx - 0.02, 4)], [round(maxy + 0.02, 4), round(maxx + 0.02, 4)]],
            "inner": box(lat, lon, 8, 7, 10, 10),
            "parramatta": box(par.y, par.x, 5.5, 5.5, 7, 7)}


def page_html(g: gpd.GeoDataFrame, stats: dict) -> str:
    """Fill the template: prose from the stats, and the data as one JSON block."""
    b = stats["bands"]
    first = lambda n: n.split(" - ")[-1]
    short = lambda n: re.sub(r"^Sydney \((North|South)\) - ", "", n)
    out_names = [n for n, _, _ in stats["outliers"]]
    ig = stats["income_groups"]
    data = {
        "breaks": BREAKS, "labels": CLASS_LABELS, "counts": stats["class_counts"],
        "median": round(stats["median"], 4), "share_mid": round(stats["share_mid"], 4),
        "n_top": stats["n_top"], "top_within_15km": stats["top_within_15km"],
        "top5": [short(n) for n, _ in stats["top5"]],
        "bands": [{"label": x["label"], "short": x["short"], "lo": BANDS[i][0], "hi": BANDS[i][1]}
                  for i, x in enumerate(b)],
        "callouts": [{"name": n, "label": n} for n in [stats["top5"][0][0]] + out_names],
        "income_groups": [{"label": x["label"], "short": x["short"], "sub": income_range(x),
                           "sub_short": f"{x['lo'] / 1000:.0f}-{x['hi'] / 1000:.0f}k"} for x in ig],
        "income_callouts": [{"name": ig[i]["top"][0], "label": ig[i]["top"][0]} for i in (0, -1)],
        "views": _views(g),
        "places": [{"name": k, "lat": v[0], "lon": v[1]} for k, v in PLACES.items()],
        "geo": _geojson(g),
    }
    text = {
        "n_scored": stats["n_scored"], "n_total": stats["n_total"], "n_unscored": stats["n_unscored"],
        "median": f"{stats['median']:.2f}", "q1": f"{stats['q1']:.2f}", "q3": f"{stats['q3']:.2f}",
        "n_top": stats["n_top"], "share_top": f"{stats['share_top']:.0%}",
        "share_mid": f"{stats['share_mid']:.0%}",
        "top_area": f"{stats['top_area_share']:.1%}", "top_people": f"{stats['top_people_share']:.0%}",
        "top_within_15km": stats["top_within_15km"],
        "band_first": f"{b[0]['median']:.2f}", "band_last": f"{b[-1]['median']:.2f}",
        "top5": ", ".join(short(n) for n, _ in stats["top5"][:-1]) + " and " + short(stats["top5"][-1][0]),
        "outliers": " and ".join(out_names), "n_outliers": stats["n_outliers"],
        "unscored_max": f"{stats['unscored_max_people']:,}",
        "corr": f"{stats['corr_income']:.2f}",
        "inc_low": f"{ig[0]['median']:.2f}", "inc_mid": f"{ig[len(ig) // 2]['median']:.2f}",
        "inc_high": f"{ig[-1]['median']:.2f}",
        "low_income_name": short(stats["lowest_income"][0]),
        "low_income_rank": int(stats["lowest_income"][2]),
        "unscored": ", ".join(stats["unscored_names"]),
        "share_top2": f"{(stats['class_counts'][0] + stats['class_counts'][1]) / stats['n_scored']:.0%}",
        "ramp_light": "".join(f"--c{i + 1}:{c};" for i, c in enumerate(RAMP)),
        "ramp_dark": "".join(f"--c{i + 1}:{c};" for i, c in enumerate(RAMP_DARK)),
    }
    page = TEMPLATE.read_text(encoding="utf-8")
    for key, value in text.items():
        page = page.replace("{{" + key + "}}", str(value) if key.startswith("ramp_") else html.escape(str(value)))
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    return page.replace("{{DATA}}", blob)


# --- Entry points -------------------------------------------------------------------------------
def build(scores, out_dir="output", page=True, images=True):
    """Write the story page and the static figures into out_dir. `scores`: CSV path or DataFrame."""
    out = Path(out_dir)
    g = load_regions(scores)
    stats = compute_stats(g)
    written = []
    if images:
        (out / "images").mkdir(parents=True, exist_ok=True)
        for name, make in (("score_distribution", figure_distribution), ("bustling_map", figure_map),
                           ("distance_from_cbd", figure_distance), ("score_by_income", figure_income)):
            fig = make(g, stats)
            path = out / "images" / f"{name}.png"
            fig.savefig(path, dpi=200)
            import matplotlib.pyplot as plt
            plt.close(fig)
            written.append(path)
    if page:
        out.mkdir(parents=True, exist_ok=True)
        path = out / "index.html"
        path.write_text(page_html(g, stats), encoding="utf-8")
        written.append(path)
    return g, stats, written


def main():
    import matplotlib
    matplotlib.use("Agg")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scores", default=str(ROOT / "expected" / "bustling_scores.csv"))
    ap.add_argument("--out", default=str(ROOT / "output"))
    ap.add_argument("--no-page", action="store_true")
    ap.add_argument("--no-images", action="store_true")
    args = ap.parse_args()
    _, _, written = build(args.scores, args.out, page=not args.no_page, images=not args.no_images)
    for path in written:
        print(f"wrote {path}  ({path.stat().st_size / 1024:,.0f} KB)")


if __name__ == "__main__":
    main()
