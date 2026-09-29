#!/usr/bin/env python3
'''Run `python3 scripts/check_vibrancy_page.py` to audit the built page in Chrome.'''

import ast
import csv
import html
import json
import math
import os
import re
import statistics
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / 'vibrancy' / 'index.html'
OUTPUT = ROOT / 'output'
DEFAULT_BROWSER = Path('/home/juanvu/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell')
BASE_HREF = 'file:///home/juanvu/DATA2001%20Assignments/vibrancy/'
BAND_ORDER = (
    'Top quintile (75 SA2s)|Second quintile (74 SA2s)|Middle quintile (75 SA2s)|'
    'Fourth quintile (74 SA2s)|Bottom quintile (74 SA2s)'
)
# The what-if weights the audit tries: Intensity, Diversity, Design (the presets and two single-pillar cases).
WHAT_IF_WEIGHTS = {
    'intensityOnly': [100, 0, 0],
    'dropDiversity': [50, 0, 50],
    'double': [50, 100, 50],
    'diversityOnly': [0, 100, 0],
    'designOnly': [0, 0, 100],
}
SA2_COUNT = 372
BUILDER_PATH = ROOT / "scripts" / "build_vibrancy_story.py"
BUILDER_CONSTANT_NAMES = {
    "PILLAR_ORDER",
    "PILLAR_CSS_NAME",
    "COLOR_ROLES",
    "PILLAR_COLORS",
    "PLACE_CSS_NAME",
    "PLACE_THEME_COLORS",
    "HOTSPOT_ORDER",
    "HOTSPOT_NAMES",
    "HOTSPOT_CSS_NAME",
}


def read_builder_constants():
    """Read the builder's colour constants without importing its geospatial libraries."""
    tree = ast.parse(BUILDER_PATH.read_text(encoding="utf-8"), filename=str(BUILDER_PATH))
    values = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if not BUILDER_CONSTANT_NAMES.intersection(names):
            continue
        statement = ast.Module(body=[node], type_ignores=[])
        exec(compile(statement, BUILDER_PATH, "exec"), values)
    missing = BUILDER_CONSTANT_NAMES.difference(values)
    assert not missing, f"Builder colour constants are missing: {sorted(missing)}"
    return types.SimpleNamespace(**{name: values[name] for name in BUILDER_CONSTANT_NAMES})


STORY_BUILDER = read_builder_constants()
# Colour expectations come from the builder, never from the rendered page.
HOTSPOT_KEYS = STORY_BUILDER.HOTSPOT_ORDER
HOTSPOT_PLAIN_NAMES = [STORY_BUILDER.HOTSPOT_NAMES[key] for key in HOTSPOT_KEYS]
HOTSPOT_COLOURS = {
    theme: [STORY_BUILDER.COLOR_ROLES[theme][STORY_BUILDER.HOTSPOT_CSS_NAME[key]] for key in HOTSPOT_KEYS]
    for theme in ["light", "dark"]
}
# SA2s whose class the audit checks on the map and in the scatterplot, one for each class.
HOTSPOT_SA2S = {
    'Darlinghurst': 'high-high', 'Blue Mountains - South': 'low-low', 'Botany': 'high-low',
    'Sydney Airport': 'low-high', 'Parramatta - North': 'not significant',
}
MORAN_AXIS_MINIMUM = 60
# The four fact lines of a card: the density column, the unit after a density (one, many) and the nouns after a
# total (one, many). A displayed 1 takes the singular. The profile card and the place cards word the density units
# a little differently (see PLACE_CARD_UNITS).
FACT_COLUMNS = [
    ('residents_per_ha', ('resident per hectare', 'residents per hectare'), ('resident', 'residents')),
    ('businesses_per_km2', ('registered business per km\u00b2', 'registered businesses per km\u00b2'),
     ('registered business', 'registered businesses')),
    ('stops_per_km2', ('stop per km\u00b2', 'stops per km\u00b2'), ('stop', 'stops')),
    ('intersections_per_km2', ('street intersection per km\u00b2', 'street intersections per km\u00b2'),
     ('street intersection', 'street intersections')),
]
PLACE_CARD_UNITS = {
    'residents_per_ha': ('resident per hectare', 'residents per hectare'),
    'businesses_per_km2': ('business per km\u00b2', 'businesses per km\u00b2'),
    'stops_per_km2': ('stop per km\u00b2', 'stops per km\u00b2'),
    'intersections_per_km2': ('intersection per km\u00b2', 'intersections per km\u00b2'),
}
# Below this density (per hectare for residents, per km2 for the rest) a card fact shows the SA2's total instead.
SMALL_DENSITY = 1
# SA2s whose displayed density is exactly 1, one for each fact: the index of that fact in FACT_COLUMNS.
SINGULAR_CASES = {
    'Berowra - Brooklyn - Cowan': 0, 'Jilliby - Yarramalong': 1, 'Sydney Airport': 2,
    'Dural - Kenthurst - Wisemans Ferry': 3,
}
# Profile cards checked: exact zeros, the largest small total (224 intersections), residents per hectare from 0.5 to 1,
# a card whose four lines are all below the 50th percentile, an unchanged high card, and the singular cases.
FACT_CARD_NAMES = [
    'Holsworthy Military Area', 'Darlinghurst', 'Calga - Kulnura', 'Terrey Hills - Duffys Forest',
    'Gosford - Springfield',
] + list(SINGULAR_CASES)
PLACE_CARD_NAMES = ['Darlinghurst', 'Sydney (South) - Haymarket', 'Gosford - Springfield', 'Wetherill Park Industrial']
# Results that are printed for the report, not judged as PASS or FAIL.
INFO_LABELS = {
    'chartGeometryDetails', 'cardBoundOffenders', 'dark screenshot pixel value', 'renderedCounts',
    'spacingDetails', 'axisDetails', 'pillarColourScan', 'textSizeDetails', 'distanceLabelDetails', 'moranSlopeDetails',
    'descendantChipSelectors',
}
TOP_FIFTH = 4
PROFILE_CHIP_SURFACES = {'light': '#fcfcfb', 'dark': '#1a1a19'}
MAP_FOCUS_STYLES = {
    'fade_opacity': 0.38,
    'full_opacity': 0.9,
    'border_weight': 0.65,
    'themes': {
        'light': {
            'fade': '#c9cbc6',
            'border': '#70726d',
            'surface': '#fcfcfb',
            'chosen': '#ffffff',
        },
        'dark': {
            'fade': '#464844',
            'border': '#b6b7b0',
            'surface': '#1a1a19',
            'chosen': '#ffffff',
        },
    },
}


def pillar_values(row):
    """Return the Intensity, Diversity and Design z-scores of one row, with None for a missing pillar."""
    names = ['intensity_z', 'diversity_z', 'design_z']
    return [float(row[name]) if row[name] != '' else None for name in names]


def weighted_averages(rows, weights):
    """Return {sa2_code: weighted mean z-score} for the SA2s that have a pillar with a weight above zero."""
    averages = {}
    for row in rows:
        total_weight = 0
        weighted_total = 0
        for value, weight in zip(pillar_values(row), weights):
            if value is not None:
                total_weight += weight
                weighted_total += value * weight
        if total_weight > 0:
            averages[row['sa2_code']] = weighted_total / total_weight
    return averages


def ranks_from_values(values_by_code, highest_first):
    """Return {code: rank}, with rank 1 for the highest value (or the lowest when highest_first is False)."""
    assert len(set(values_by_code.values())) == len(values_by_code), 'ties would make the ranks ambiguous'
    ordered = sorted(values_by_code, key=lambda code: values_by_code[code], reverse=highest_first)
    return {code: position + 1 for position, code in enumerate(ordered)}


def pearson(first, second):
    """Return the Pearson correlation of two equal-length lists."""
    count = len(first)
    first_mean = sum(first) / count
    second_mean = sum(second) / count
    covariance = sum((x - first_mean) * (y - second_mean) for x, y in zip(first, second))
    first_spread = sum((x - first_mean) ** 2 for x in first)
    second_spread = sum((y - second_mean) ** 2 for y in second)
    return covariance / math.sqrt(first_spread * second_spread)


def fifth_of(rank, count):
    """Return the fifth (4 is the top fifth) of a rank when count SA2s are ranked."""
    return 4 - (rank - 1) * 5 // count


def moves_sentence(changed):
    """Return the sentence that says how many SA2s move to a different quintile."""
    if changed == 0:
        return 'No SA2 moves to a different quintile.'
    if changed == 1:
        return '1 SA2 moves to a different quintile.'
    return f'{changed} SA2s move to a different quintile.'


def expected_summary(spearman_text, kept_top_25, kept_top_quintile, top_quintile_total):
    """Return the what-if summary sentence shared by the weight and sensitivity-variant modes."""
    return (f'Spearman correlation with the baseline ranking: {spearman_text}. '
            f'{kept_top_25} of the baseline\u2019s top 25 stay in the top 25. '
            f'{kept_top_quintile} of the baseline\u2019s {top_quintile_total} top-quintile SA2s stay in the top quintile.')


def rank_ranges_by_class(ranks, classes):
    """Return the lowest and highest rank in each quintile class, for the weights-mode legend text."""
    ranges = {}
    for code, level in classes.items():
        rank = ranks[code]
        if level not in ranges:
            ranges[level] = {'min': rank, 'max': rank}
        else:
            ranges[level]['min'] = min(ranges[level]['min'], rank)
            ranges[level]['max'] = max(ranges[level]['max'], rank)
    return ranges


def rank_range_legend_labels(ranges):
    """Return the five rank-range legend labels (without counts) in top-to-bottom quintile order."""
    names = ['Top quintile', 'Second quintile', 'Middle quintile', 'Fourth quintile', 'Bottom quintile']
    return [f'{name}: ranks {ranges[4 - index]["min"]} to {ranges[4 - index]["max"]}' for index, name in enumerate(names)]


def weights_expectations(scored, weights):
    """Work out, from the saved scores alone, what the page must show under one set of weights."""
    averages = weighted_averages(scored, weights)
    count = len(averages)
    mean = sum(averages.values()) / count
    population_sd = math.sqrt(sum((value - mean) ** 2 for value in averages.values()) / count)
    scores = {code: 100 + 10 * (value - mean) / population_sd for code, value in averages.items()}
    ranks = ranks_from_values(averages, True)
    baseline = {row['sa2_code']: row for row in scored}
    baseline_ranks = {code: int(baseline[code]['vibrancy_rank']) for code in averages}
    baseline_order = ranks_from_values(baseline_ranks, False)
    correlation = pearson([baseline_order[code] for code in averages], [ranks[code] for code in averages])
    baseline_fifth = {code: int(row['vibrancy_quintile']) - 1 for code, row in baseline.items()}
    weighted_fifth = {code: fifth_of(ranks[code], count) for code in averages}
    top_total = sum(1 for fifth in baseline_fifth.values() if fifth == TOP_FIFTH)
    kept = sum(1 for code in averages if baseline_fifth[code] == TOP_FIFTH and weighted_fifth[code] == TOP_FIFTH)
    baseline_top_25 = {code for code in baseline if int(baseline[code]['vibrancy_rank']) <= 25}
    kept_top_25 = sum(1 for code in baseline_top_25 if code in ranks and ranks[code] <= 25)
    fifth_counts = [sum(1 for fifth in weighted_fifth.values() if fifth == level) for level in [4, 3, 2, 1, 0]]
    gaps = sorted(((abs(ranks[code] - baseline_ranks[code]), code) for code in averages), reverse=True)
    movers = [[baseline[code]['sa2_name'], baseline_ranks[code], ranks[code]] for _, code in gaps[:15]]
    shares = [round(weight / sum(weights) * 100) for weight in weights]
    no_score_names = [row['sa2_name'] for row in scored if row['sa2_code'] not in averages]
    rank_ranges = rank_ranges_by_class(ranks, weighted_fifth)
    return {
        'weights': weights,
        'shares': shares,
        'count': count,
        'no_score': SA2_COUNT - count,
        'no_score_names': no_score_names,
        'spearman': f'{correlation:.2f}',
        'kept_top_25': kept_top_25,
        'kept': kept,
        'top_total': top_total,
        'summary': expected_summary(f'{correlation:.2f}', kept_top_25, kept, top_total),
        'legend_labels': rank_range_legend_labels(rank_ranges),
        'fifth_counts': fifth_counts,
        'fifths': weighted_fifth,
        'ranks': ranks,
        'scores': scores,
        'move_gaps': [gap for gap, _ in gaps[:15]],
        'movers': movers,
    }


def expected_intensity_only_parity(scored):
    """Verify that Intensity-only weights and the 'Intensity only' sensitivity variant give every
    scored SA2 the identical rank (the owner's own check), and return the one summary and legend
    both what-if modes must show for that shared ranking."""
    with (OUTPUT / 'vibrancy_variant_ranks.csv').open(encoding='utf-8') as handle:
        variant_rows = {row['sa2_code']: row for row in csv.DictReader(handle)}
    weighted = weights_expectations(scored, [100, 0, 0])
    variant_ranks = {code: int(variant_rows[code]['Intensity only']) for code in weighted['ranks']}
    assert variant_ranks == weighted['ranks'], 'Intensity-only weights and variant do not share a ranking'
    return {'summary': weighted['summary'], 'legend_labels': weighted['legend_labels']}


def zero_comparison_text(zero_count, total):
    """Return how the card describes a zero value that zero_count of total scored SA2s share."""
    if zero_count == 1:
        return 'none, as in no other SA2'
    share = zero_count / total * 100
    if share < 1:
        return 'none, as in fewer than 1% of SA2s'
    return f'none, as in {int(share + 0.5)}% of SA2s'


def fact_total(row, column):
    """Return the whole-number total behind one fact: the residents column, or density times area."""
    if column == 'residents_per_ha':
        return int(row['residents'])
    return round(float(row[column]) * float(row['area_km2']))


def density_comparison_text(values, value):
    """Say how a non-zero density compares with all the scored SA2s.

    From the 50th percentile up: "higher than X%", X being the share at or below the value. Below it:
    "lower than Y%", Y being the share strictly above the value. Halves round up and 99 is the cap.
    """
    at_or_below = sum(1 for other in values if other <= value)
    if at_or_below * 2 >= len(values):
        return f'higher than {min(99, int(at_or_below / len(values) * 100 + 0.5))}% of SA2s'
    above = sum(1 for other in values if other > value)
    return f'lower than {min(99, int(above / len(values) * 100 + 0.5))}% of SA2s'


def expected_fact_lines(scored, name, place_card=False):
    """Return the four [value text, comparison text] lines a card must show for one SA2.

    A place card also writes "the highest of N SA2s" for the largest value and uses its own unit wording.
    """
    row = next(item for item in scored if item['sa2_name'] == name)
    lines = []
    for column, units, nouns in FACT_COLUMNS:
        values = [float(item[column]) for item in scored]
        value = float(row[column])
        if value < SMALL_DENSITY:
            total = fact_total(row, column)
            first = f'{total:,} {nouns[0] if total == 1 else nouns[1]} in total'
            if value == 0:
                second = zero_comparison_text(sum(1 for other in values if other == 0), len(values))
            else:
                second = 'density ' + density_comparison_text(values, value)
        else:
            shown = int(value + 0.5)
            unit = (PLACE_CARD_UNITS[column] if place_card else units)[0 if shown == 1 else 1]
            first = f'{shown:,} {unit}'
            second = density_comparison_text(values, value)
            if place_card and value >= max(values):
                second = f'the highest of {len(values)} SA2s'
        lines.append([first, second])
    return lines


def fact_lines_with_checked_singular_cases(scored):
    """Return the expected profile-card lines, after checking each singular case really shows a displayed 1."""
    lines = {name: expected_fact_lines(scored, name) for name in FACT_CARD_NAMES}
    for name, index in SINGULAR_CASES.items():
        first = lines[name][index][0]
        assert first.startswith('1 ') and ' in total' not in first, f'{name} should show a density of 1: {first}'
    return lines


def expected_foot_correlations():
    """Return the weekday and weekend Spearman correlations, formatted as the page's placeholders are."""
    foot = read_rows('vibrancy_foot_traffic_check.csv')
    return {row['day_type']: f"{float(row['spearman']):.2f}" for row in foot}


def expected_rank_bands(scored):
    """Compute the five stability summaries from the saved scores, independently of the page."""
    quintiles = [
        ('Top quintile', 1, 75), ('Second quintile', 76, 149),
        ('Middle quintile', 150, 224), ('Fourth quintile', 225, 298),
        ('Bottom quintile', 299, 372),
    ]
    summaries = []
    for label, first, last in quintiles:
        band = [row for row in scored if first <= int(row['vibrancy_rank']) <= last]
        ranges = [int(row['rank_max']) - int(row['rank_min']) for row in band]
        mover = sorted(
            band,
            key=lambda row: (
                -(int(row['rank_max']) - int(row['rank_min'])),
                int(row['vibrancy_rank']),
                row['sa2_name'],
            ),
        )[0]
        summaries.append({
            'label': f'{label} ({len(band)} SA2s)', 'sa2s': len(band),
            'median': float(statistics.median(ranges)), 'maximum': float(max(ranges)),
            'mover_name': mover['sa2_name'], 'mover_rank_min': int(mover['rank_min']),
            'mover_rank_max': int(mover['rank_max']),
        })
    return summaries


def expected_foot_top_names():
    """Return the top-3-by-count SA2 names for each day, from the saved foot-traffic CSV, not the page."""
    foot = read_rows('vibrancy_foot_traffic_sa2.csv')
    return {
        day: [row['sa2_name'] for row in sorted(foot, key=lambda row: -float(row[day + '_average']))[:3]]
        for day in ['weekday', 'weekend']
    }


def expected_distance_colours(scored):
    """Return every scored SA2's true rank-fifth colour in both themes, from its saved quintile, not the page."""
    colours = {}
    for row in scored:
        quintile = int(row['vibrancy_quintile'])
        colours[row['sa2_name']] = {
            theme: STORY_BUILDER.COLOR_ROLES[theme][f'fifth-{quintile}'] for theme in ['light', 'dark']
        }
    return colours


def expected_quintiles(scored):
    """Return every scored SA2's own overall quintile (0 bottom to 4 top), from the saved rank, not the page."""
    return {row['sa2_name']: int(row['vibrancy_quintile']) - 1 for row in scored}


def expected_pillar_quintiles(scored):
    """Return every scored SA2's own quintile on each pillar, ranked from the saved pillar scores, not the page."""
    quintiles = {}
    for label in STORY_BUILDER.PILLAR_ORDER:
        column = label.lower() + '_score'
        available = sorted(
            (row for row in scored if row[column] != ''),
            key=lambda row: float(row[column]),
            reverse=True,
        )
        quintiles[label.lower()] = {
            row['sa2_name']: fifth_of(rank, len(available)) for rank, row in enumerate(available, start=1)
        }
    return quintiles


def expected_quintile_ramp():
    """Return the five true overall-quintile colours in each theme, bottom (0) to top (4), from the builder."""
    return {theme: [STORY_BUILDER.COLOR_ROLES[theme][f'fifth-{level}'] for level in range(1, 6)] for theme in ['light', 'dark']}


def expected_below_axis_note(scored):
    """Return the note under the distance chart about SA2s that score below the 70 axis."""
    count = sum(1 for row in scored if float(row['vibrancy_score']) < 70)
    if count == 0:
        return ''
    if count == 1:
        return '1 SA2 below 70 is drawn on the bottom axis line; hover the dot for its true score.'
    return f'{count} SA2s below 70 are drawn on the bottom axis line; hover a dot for its true score.'


def read_rows(filename):
    """Read one saved output table as a list of dictionaries."""
    with (OUTPUT / filename).open(encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def join_names(names):
    """Join names for a sentence: "A", "A and B", or "A, B and C"."""
    if len(names) <= 1:
        return ''.join(names)
    return ', '.join(names[:-1]) + ' and ' + names[-1]


def expected_moran_text(scored, hotspots, global_i):
    """Return the Moran card's title and paragraphs, worked out from the CSVs (population and areas from the scores)."""
    by_class = {key: sorted(row['sa2_name'] for row in hotspots if row['hotspot_class'] == key) for key in HOTSPOT_KEYS}
    low_low_codes = {row['sa2_code'] for row in hotspots if row['hotspot_class'] == 'low-low'}
    low_low = [row for row in scored if row['sa2_code'] in low_low_codes]
    resident_share = sum(int(row['residents']) for row in low_low) / sum(int(row['residents']) for row in scored)
    area_share = sum(float(row['area_km2']) for row in low_low) / sum(float(row['area_km2']) for row in scored)
    high_high, low_count = len(by_class['high-high']), len(by_class['low-low'])
    outliers = []
    for key, direction in [('high-low', 'high among lower-scoring neighbours'), ('low-high', 'low among higher-scoring ones')]:
        if by_class[key]:
            verb = 'scores' if len(by_class[key]) == 1 else 'score'
            outliers.append(f'{join_names(by_class[key])} {verb} {direction}.')
    low_low_sentence = (f'The {low_count} low-low SA2s hold {resident_share:.1%} of residents but cover '
                        f'{area_share:.1%} of the land we scored')
    if area_share > 2 * resident_share:
        low_low_sentence += ', so the group is mostly large, sparsely populated areas'
    return {
        'title': f'Neighbouring SA2s tend to score alike: {high_high} high-high and {low_count} low-low clusters',
        'paragraphs': [
            "Moran's I asks whether neighbouring SA2s look alike. A value of 0 means no pattern and 1 means neighbours "
            f'look exactly alike; here it is {global_i:.2f}, so nearby SA2s often score alike.',
            f'Of the {len(scored)} scored SA2s, {high_high} are high-high (a high score with high-scoring neighbours) and '
            f'{low_count} are low-low (a low score with low-scoring neighbours). {" ".join(outliers)} '
            f'The other {len(by_class["not significant"])} are not clusters.',
            low_low_sentence + '.',
            'Clusters are descriptive: no correction is made for testing many areas.',
        ],
    }


def expected_moran_axis_note(scored):
    """Return the note about SA2s that score below the scatterplot's axis start."""
    left = sorted((float(row['vibrancy_score']), row['sa2_name']) for row in scored if float(row['vibrancy_score']) < MORAN_AXIS_MINIMUM)
    if not left:
        return ''
    named = ', '.join(f'{name} (score {score:.1f})' for score, name in left)
    subject = '1 SA2 is' if len(left) == 1 else f'{len(left)} SA2s are'
    return f'{subject} left of the axis: {named}.'


def hotspot_expectations(scored):
    """Return what the Hot spots layer, the tooltips, the cards and the Moran chart must show, from the CSVs."""
    hotspots = read_rows('vibrancy_hotspots.csv')
    global_i = float(read_rows('vibrancy_hotspot_global.csv')[0]['global_morans_i'])
    counts = {key: sum(1 for row in hotspots if row['hotspot_class'] == key) for key in HOTSPOT_KEYS}
    scores = {row['sa2_code']: row for row in scored}
    by_name = {row['sa2_name']: row for row in hotspots}
    own = [float(scores[row['sa2_code']]['vibrancy_score']) - 100 for row in hotspots]
    neighbours = [float(row['neighbour_average_score']) - 100 for row in hotspots]
    across = sum(first * second for first, second in zip(own, neighbours))
    along = sum(first ** 2 for first in own)
    tooltips, card_lines = {}, {}
    for name in ['Sydney Airport', 'Botany']:
        row, score = by_name[name], scores[by_name[name]['sa2_code']]
        plain = HOTSPOT_PLAIN_NAMES[HOTSPOT_KEYS.index(row['hotspot_class'])]
        shown = f'{float(score["vibrancy_score"]):.1f}'
        neighbour_text = f'{float(row["neighbour_average_score"]):.1f}'
        tooltips[name] = [
            name, plain, f"Score {shown}, neighbours' average {neighbour_text}",
            f'Vibrancy score {shown}, rank {score["vibrancy_rank"]} of {SA2_COUNT}', f'Evidence: p = {float(row["p_value"]):.3f}',
        ]
        kind = 'cluster' if row['hotspot_class'] in ('high-high', 'low-low') else 'outlier'
        card_lines[name] = [f'Hot spot: {row["hotspot_class"]} {kind}', f"Neighbours' average score: {neighbour_text}"]
    return {
        'legend': [f'{name} ({counts[key]})' for key, name in zip(HOTSPOT_KEYS, HOTSPOT_PLAIN_NAMES)] + ['Not scored'],
        'classes': {name: by_name[name]['hotspot_class'] for name in HOTSPOT_SA2S},
        'class_by_code': {row['sa2_code']: row['hotspot_class'] for row in hotspots},
        'dots': sum(1 for row in hotspots if float(scores[row['sa2_code']]['vibrancy_score']) >= MORAN_AXIS_MINIMUM),
        'axis_note': expected_moran_axis_note(scored),
        'global_i': global_i,
        'recomputed_slope': across / along,
        'text': expected_moran_text(scored, hotspots, global_i),
        'tooltips': tooltips,
        'card_lines': card_lines,
    }




def colour_expectations(scored):
    """Return D18 map and component colours from the builder and saved score ranks."""
    darlinghurst = next(row for row in scored if row["sa2_name"] == "Darlinghurst")
    pillar_fifths = {}
    for label in STORY_BUILDER.PILLAR_ORDER:
        column = label.lower() + "_score"
        available = sorted(
            (row for row in scored if row[column] != ""),
            key=lambda row: float(row[column]),
            reverse=True,
        )
        rank = next(index + 1 for index, row in enumerate(available) if row["sa2_code"] == darlinghurst["sa2_code"])
        pillar_fifths[label.lower()] = fifth_of(rank, len(available))
    representatives = {}
    for row in scored:
        representatives.setdefault(row["place_type"], row["sa2_name"])
    themes = {}
    for theme in ["light", "dark"]:
        roles = STORY_BUILDER.COLOR_ROLES[theme]
        pillar = {}
        for label in STORY_BUILDER.PILLAR_ORDER:
            name = label.lower()
            palette = STORY_BUILDER.PILLAR_COLORS[theme][label]
            pillar[name] = {
                "ramp": palette["ramp"],
                "text": palette["text"],
                "bar": palette["bar"],
                "known_fill": palette["ramp"][pillar_fifths[name]],
            }
        ink_labels = {"less dense and less diverse"}
        if theme == "light":
            ink_labels.add("dense and less diverse")
        place_text = {label: roles["ink"] if label in ink_labels else PROFILE_CHIP_SURFACES[theme]
                      for label in STORY_BUILDER.PLACE_CSS_NAME}
        themes[theme] = {
            "overall_fill": roles[f"fifth-{int(darlinghurst['vibrancy_quintile'])}"],
            "pillar": pillar,
            "place": STORY_BUILDER.PLACE_THEME_COLORS[theme],
            "place_text": place_text,
            "ink": roles["ink"],
        }
    return {
        "themes": themes,
        "place_representatives": representatives,
        "place_card_names": PLACE_CARD_NAMES,
        "known_name": darlinghurst["sa2_name"],
    }
def expected_values():
    """Read the values compared with page interactions."""
    scores_path = OUTPUT / 'vibrancy_scores.csv'
    ranks_path = OUTPUT / 'vibrancy_variant_ranks.csv'
    if not scores_path.exists() or not ranks_path.exists():
        return {}
    with scores_path.open(encoding='utf-8') as handle:
        scores = list(csv.DictReader(handle))
    scored = [row for row in scores if row['scored'] == 'True']
    intensity_top = [row['sa2_name'] for row in sorted(scored, key=lambda row: float(row['intensity_score']), reverse=True)[:5]]
    with ranks_path.open(encoding='utf-8') as handle:
        ranks = list(csv.DictReader(handle))
    equal = sorted(ranks, key=lambda row: int(row['Equal per indicator']))
    what_if = {name: weights_expectations(scored, weights) for name, weights in WHAT_IF_WEIGHTS.items()}
    return {'intensity_top': intensity_top, 'equal_top': [row['sa2_name'] for row in equal[:10]],
            'equal_ranks': {row['sa2_code']: int(row['Equal per indicator']) for row in ranks},
            'hotspots': hotspot_expectations(scored),
            'hotspot_colours': HOTSPOT_COLOURS,
            'hotspot_sa2s': HOTSPOT_SA2S,
            'map_focus': MAP_FOCUS_STYLES,
            'colours': colour_expectations(scored),
            'fact_lines': fact_lines_with_checked_singular_cases(scored),
            'singular_cases': SINGULAR_CASES,
            'place_card_facts': {name: expected_fact_lines(scored, name, place_card=True) for name in PLACE_CARD_NAMES},
            'below_axis_note': expected_below_axis_note(scored),
            'distance': {'colours': expected_distance_colours(scored)},
            'quintiles': expected_quintiles(scored),
            'pillar_quintiles': expected_pillar_quintiles(scored),
            'quintile_ramp': expected_quintile_ramp(),
            'place_card_names': PLACE_CARD_NAMES,
            'rank_bands': expected_rank_bands(scored),
            'foot_correlations': expected_foot_correlations(),
            'foot_top_names': expected_foot_top_names(),
            'what_if': what_if, 'moves_sentences': {str(count): moves_sentence(count) for count in [0, 1, 2, 102]},
            'intensity_only_parity': expected_intensity_only_parity(scored)}


def browser_path():
    '''Return the configured browser path, or the checked-in default.'''
    return Path(os.environ.get('VIBRANCY_CHROME', DEFAULT_BROWSER))


def injected_script(mode):
    """Read the browser checks and inject their theme and expected values."""
    theme = mode
    source = (ROOT / "scripts" / "check_vibrancy_page.js").read_text(encoding="utf-8")
    source = source.replace("{{THEME}}", theme)
    source = source.replace("{{EXPECTED}}", json.dumps(expected_values()))
    return "<script>\n" + source + "</script>"



def write_check_page(mode):
    '''Write one local page copy with a base URL and browser-side checks.'''
    page = PAGE.read_text(encoding='utf-8')
    page = page.replace('<head>', f'<head><base href="{BASE_HREF}">', 1)
    page = page.replace('</body>', injected_script(mode) + '</body>', 1)
    path = OUTPUT / f'vibrancy_page_check_{mode}.html'
    path.write_text(page, encoding='utf-8')
    return path


def take_state_screenshot(browser, shot, width, height):
    """Save one screenshot of a page state: the What if drawer after a preset, or the Holsworthy profile card."""
    source = (ROOT / 'scripts' / 'check_vibrancy_shots.js').read_text(encoding='utf-8').replace('{{SHOT}}', shot)
    page = PAGE.read_text(encoding='utf-8')
    page = page.replace('<head>', f'<head><base href="{BASE_HREF}">', 1)
    page = page.replace('</body>', '<script>\n' + source + '</script></body>', 1)
    page_path = OUTPUT / f'vibrancy_page_check_{shot}.html'
    page_path.write_text(page, encoding='utf-8')
    screenshot_path = OUTPUT / f'vibrancy_page_check_{shot}.png'
    command = [str(browser), '--headless', '--no-sandbox', '--disable-gpu', '--virtual-time-budget=20000',
               f'--screenshot={screenshot_path}', f'--window-size={width},{height}', page_path.as_uri()]
    subprocess.run(command, text=True, capture_output=True, check=False)
    return screenshot_path


def read_results(dom):
    '''Read the injected JSON result from a dumped page.'''
    match = re.search(r'<pre id="check-results">(.*?)</pre>', dom, re.DOTALL)
    if not match:
        return None
    return json.loads(html.unescape(match.group(1)))



def png_corner_pixel(path, x=5, y=5):
    """Read one RGB pixel from a non-interlaced Chrome PNG without extra packages."""
    import struct
    import zlib

    data = path.read_bytes()
    offset = 8
    width = height = color_type = None
    compressed = b""
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        chunk = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
            assert depth == 8 and interlace == 0
        if kind == b"IDAT":
            compressed += chunk
        if kind == b"IEND":
            break
    channels = 4 if color_type == 6 else 3
    stride = width * channels
    raw = zlib.decompress(compressed)
    rows = []
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        row = list(raw[position:position + stride])
        position += stride
        previous = rows[-1] if rows else [0] * stride
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (value + left) % 256
            elif filter_type == 2:
                row[index] = (value + above) % 256
            elif filter_type == 3:
                row[index] = (value + (left + above) // 2) % 256
            elif filter_type == 4:
                pa = abs(above - upper_left)
                pb = abs(left - upper_left)
                pc = abs(left + above - 2 * upper_left)
                predictor = left if pa <= pb and pa <= pc else above if pb <= pc else upper_left
                row[index] = (value + predictor) % 256
        rows.append(row)
    start = x * channels
    return tuple(rows[y][start:start + 3])


def run_mode(browser, mode, width):
    '''Run one page mode and return named pass or fail checks.'''
    check_page = write_check_page(mode)
    dom_path = OUTPUT / f'vibrancy_page_check_{mode}_dom.html'
    log_path = OUTPUT / f'vibrancy_page_check_{mode}_console.txt'
    screenshot_path = OUTPUT / f'vibrancy_page_check_{mode}.png'
    page_height = 7600 if width >= 1000 else 9000
    command = [
        str(browser),
        '--headless',
        '--no-sandbox',
        '--disable-gpu',
        '--virtual-time-budget=20000',
        '--dump-dom',
        f'--screenshot={screenshot_path}',
        '--enable-logging=stderr',
        '--v=0',
        f'--window-size={width},{page_height}',
        check_page.as_uri(),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    dom_path.write_text(result.stdout, encoding='utf-8')
    log_path.write_text(result.stderr, encoding='utf-8')
    checks = read_results(result.stdout) or {'injected checks': False}
    checks['console'] = result.returncode == 0 and 'CONSOLE' not in result.stderr and 'ERROR' not in result.stderr
    if mode == 'dark':
        pixel = png_corner_pixel(screenshot_path)
        checks['dark screenshot pixel'] = max(abs(channel - 13) for channel in pixel) <= 8
        checks['dark screenshot pixel value'] = pixel
    if width >= 1000:
        checks.pop('phoneCards', None)
    else:
        checks.pop('wideCards', None)
    return checks




def mutation_checks(browser):
    """Prove colour and fade checks fail on temporary copies while the built page stays byte-identical."""
    original = PAGE.read_bytes()
    expected = expected_values()["colours"]["themes"]["light"]
    source = original.decode("utf-8")
    wrong_layer = source
    for current_colour, replacement_colour in zip(
        STORY_BUILDER.PILLAR_COLORS["light"]["Intensity"]["ramp"],
        STORY_BUILDER.PILLAR_COLORS["light"]["Design"]["ramp"],
    ):
        wrong_layer = wrong_layer.replace(current_colour, replacement_colour, 1)
    uncoloured_slider = source.replace(
        "</style>",
        "#what-if label.intensity{color:var(--ink)!important}\n</style>",
        1,
    )
    place_token = "--place-dense-diverse:" + expected["place"]["dense and diverse"]
    mutated_place_colour = source.replace(place_token, "--place-dense-diverse:#2E8B57", 1)
    fixed_profile_markup = (
        "        '<span class=\"type-' + placeClass(properties.place_type) + '\">',\n"
        "        '<span class=\"type-chip\">' + textValue(properties.place_type) + '</span>',\n"
        "        '</span>',"
    )
    broken_profile_markup = (
        "        '<span class=\"type-chip type-' + placeClass(properties.place_type) + '\">',\n"
        "        textValue(properties.place_type) + '</span>',"
    )
    broken_profile_chip = source.replace(fixed_profile_markup, broken_profile_markup, 1)
    skipped_fade = source.replace(
        "const faded = categoryIsFaded(properties) && !chosen && !highlighted;",
        "const faded = false;",
        1,
    )
    skipped_distance_fade = source.replace(
        "cx: x, cy: y, r: 3.5, fill: fade, class: 'dot'",
        "cx: x, cy: y, r: 3.5, fill: ramp[properties.rank_class], class: 'dot'",
        1,
    )
    skipped_scatter_fade = source.replace(
        "r: 3.5, fill: isExample ? ramp[properties.rank_class] : fade, class: 'dot',",
        "r: 3.5, fill: ramp[properties.rank_class], class: 'dot',",
        1,
    )
    skipped_foot_fade = source.replace(
        "cx: x, cy: y, r: 4, fill: fade, class: 'dot'",
        "cx: x, cy: y, r: 4, fill: ramp[properties.rank_class], class: 'dot'",
        1,
    )
    skipped_chart_quintile_fade = source.replace(
        "dot.setAttribute('fill', properties.rank_class === focus ? ramp[focus] : fade);",
        "dot.setAttribute('fill', ramp[focus]);",
        1,
    )
    skipped_map_quintile_fade = source.replace(
        "return colourIndex !== focus;",
        "return false;",
        1,
    )
    first_band = expected_values()["rank_bands"][0]
    wrong_stability_range = source.replace(
        '"mover_name":' + json.dumps(first_band["mover_name"]),
        '"mover_name":"Wrong SA2"',
        1,
    )
    wrong_stability_range = wrong_stability_range.replace(
        '"mover_rank_max":' + str(first_band["mover_rank_max"]),
        '"mover_rank_max":999', 1,
    )
    reverted_ring_colour = source.replace("--chosen-ring:#ffffff;", "--chosen-ring:#343434;", 1)
    skipped_ring_halo = source.replace(
        "element.classList.toggle('chosen-halo', String(item.feature.properties.id) === selectedCode);",
        "element.classList.toggle('chosen-halo', false);",
        1,
    )
    assert broken_profile_chip != source
    assert skipped_fade != source
    assert skipped_distance_fade != source
    assert skipped_scatter_fade != source
    assert skipped_foot_fade != source
    assert skipped_chart_quintile_fade != source
    assert skipped_map_quintile_fade != source
    assert wrong_stability_range != source
    assert reverted_ring_colour != source
    assert skipped_ring_halo != source
    cases = [
        (
            "wrong pillar hue",
            wrong_layer,
            {"layerFill", "pillarLayerColours-light", "intensityQuintileFocus-light"},
            True,
        ),
        ("uncoloured slider label", uncoloured_slider, {"pillarSliderColours-light", "pillarSliderColours-dark"}, True),
        (
            "prior place-type colour",
            mutated_place_colour,
            {
                "placeTypeColours-light", "profilePlaceTypeColours-light",
                "placeLegendFocus-light", "placeLegendRestore-light",
                "placeTableFocus-light", "placeTableRestore-light",
                "independentFocus-light",
            },
            True,
        ),
        (
            "broken profile chip markup",
            broken_profile_chip,
            {"profilePlaceTypeColours-light", "profilePlaceTypeColours-dark"},
            True,
        ),
        (
            "skipped fade branch",
            skipped_fade,
            {"placeLegendFocus-light", "placeTableFocus-light", "hotspotLegendFocus-light"},
            False,
        ),
        (
            "skipped distance fade",
            skipped_distance_fade,
            {"distanceFade"},
            True,
        ),
        (
            "skipped scatter fade",
            skipped_scatter_fade,
            {"intensity-design-chartFade", "density-diversity-chartFade"},
            True,
        ),
        (
            "skipped foot fade",
            skipped_foot_fade,
            {"weekdayFade", "weekendFade"},
            True,
        ),
        (
            "skipped chart quintile fade",
            skipped_chart_quintile_fade,
            # weekday-chart/weekend-chart are excluded: every site they plot is in the top quintile
            # (the only quintile with a button there), so focusing it never needs to fade anything,
            # and this mutation has nothing to break on those two charts.
            {
                "distance-chartQuintileFocus", "intensity-design-chartQuintileFocus",
                "density-diversity-chartQuintileFocus",
            },
            True,
        ),
        (
            "skipped map quintile fade",
            skipped_map_quintile_fade,
            {
                "overallQuintileFocus-light", "overallQuintileFocus-dark",
                "intensityQuintileFocus-light", "intensityQuintileFocus-dark",
                "diversityQuintileFocus-light", "diversityQuintileFocus-dark",
                "designQuintileFocus-light", "designQuintileFocus-dark",
            },
            True,
        ),
        ("wrong stability range and name", wrong_stability_range, {"stabilityQuintiles"}, True),
        (
            "reverted chosen ring colour",
            reverted_ring_colour,
            {
                "chosenRingColour-light", "chosenRingCentennialPark-light",
                "focusOverrides-light", "quintileFocusOverrides-light",
            },
            True,
        ),
        (
            "skipped chosen ring halo",
            skipped_ring_halo,
            {
                "chosenRingHalo-light", "chosenRingHalo-dark",
                "chosenRingCentennialPark-light", "chosenRingCentennialPark-dark",
            },
            True,
        ),
    ]
    results = {}
    import tempfile
    with tempfile.TemporaryDirectory(dir=OUTPUT) as directory:
        temporary = Path(directory)
        for label, page, failed_checks, exact_failure in cases:
            page = page.replace("<head>", f'<head><base href="{BASE_HREF}">', 1)
            page = page.replace("</body>", injected_script("light") + "</body>", 1)
            page_path = temporary / (re.sub(r"[^a-z]+", "_", label) + ".html")
            page_path.write_text(page, encoding="utf-8")
            command = [
                str(browser),
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--virtual-time-budget=20000",
                "--window-size=1280,7600",
                "--dump-dom",
                page_path.as_uri(),
            ]
            run = subprocess.run(command, text=True, capture_output=True, check=False)
            checks = read_results(run.stdout) or {}
            observed_failures = {key for key, value in checks.items() if value is False}
            expected_failures = all(checks.get(check) is False for check in failed_checks)
            if exact_failure:
                expected_failures = expected_failures and observed_failures == failed_checks
            results[label] = run.returncode == 0 and expected_failures
    results["temporary page restored byte for byte"] = PAGE.read_bytes() == original
    return results
def main():
    '''Print each browser audit result and return a failure status when needed.'''
    browser = browser_path()
    if not browser.exists():
        print(f'SKIP browser check: Chrome not found at {browser}')
        return 0
    if not PAGE.exists():
        print(f'FAIL page is missing: {PAGE}')
        return 1
    runs = [('light', 1280), ('dark', 1280), ('phone', 390)]
    passed = True
    for mode, width in runs:
        checks = run_mode(browser, mode, width)
        for label, result in checks.items():
            if label in INFO_LABELS:
                print(f'INFO {mode}: {label} {result}')
                continue
            state = 'PASS' if result else 'FAIL'
            print(f'{state} {mode}: {label}')
            passed = passed and bool(result)
    for label, result in mutation_checks(browser).items():
        state = 'PASS' if result else 'FAIL'
        print(f'{state} mutation: {label}')
        passed = passed and bool(result)
    screenshots = [
        ('whatif', 1700), ('intensity', 1000), ('diversity', 1000), ('placetypes', 1000),
        ('cards', 1700), ('holsworthy', 1000), ('hotspots', 1000), ('moran', 700),
        ('distance', 650), ('distancedark', 650), ('distancequintile', 650), ('histogram', 650),
        ('intensitydesign', 650), ('densitydiversity', 650),
        ('stability', 750), ('footpanel', 1300),
        ('weekdayscatter', 650), ('weekendscatter', 650),
        ('typefocus', 1000), ('hotspotfocus', 1000), ('overallquintile', 1000),
        ('selected', 1000), ('selecteddark', 1000), ('centennial', 1000),
    ]
    for shot, height in screenshots:
        print(f'INFO screenshot: {take_state_screenshot(browser, shot, 1280, height)}')
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
