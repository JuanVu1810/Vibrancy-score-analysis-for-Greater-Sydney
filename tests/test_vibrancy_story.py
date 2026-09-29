"""Checks for the local Greater Sydney story-page build."""

import html
import importlib.util
import json
import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_vibrancy_story.py"


def story_builder():
    """Load the copied story builder as a testable module."""
    specification = importlib.util.spec_from_file_location("vibrancy_story", BUILDER_PATH)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def fixture_scores():
    """Return five scored SA2s and one excluded SA2 for page checks.

    Echo uses a real SA2 far from the CBD (Blue Mountains - South) so the distance chart's near
    and far bands both have a row; the other codes are ordinary inner-city SA2s.
    """
    names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Excluded"]
    place_types = [
        "dense and diverse", "dense and less diverse", "less dense and diverse",
        "less dense and less diverse", "dense and diverse", "",
    ]
    rows = []
    for position, name in enumerate(names):
        rank = position + 1
        scored = position < 5
        rows.append({
            "sa2_code": [117031329, 117031330, 117031331, 117031333, 124021456, 117031638][position],
            "sa2_name": name,
            "residents": 1000 + position * 100,
            "median_income": None if position == 1 else 70000 + position * 1000,
            "businesses": 100 + position,
            "businesses_per_km2": 10 + position,
            "area_km2": 10.0,
            "residents_per_ha": 5 + position,
            "stops_per_km2": 2 + position,
            "intersections_per_km2": 3 + position,
            "intensity_z": 2 - position * 0.5 if scored else None,
            "diversity_z": None if position == 2 else (1 - position * 0.25 if scored else None),
            "design_z": 1.5 - position * 0.4 if scored else None,
            "vibrancy_score": 120 - position * 10 if scored else None,
            "intensity_score": 118 - position * 9 if scored else None,
            "diversity_score": 105 - position * 4 if scored else None,
            "design_score": 112 - position * 6 if scored else None,
            "vibrancy_rank": rank if scored else None,
            "vibrancy_quintile": 6 - rank if scored else None,
            "place_type": place_types[position],
            "hotspot_class": "high-high" if position == 0 else "not significant",
            "rank_min": rank if scored else None,
            "rank_max": rank + 1 if scored else None,
            "flag": "Missing D1 and D2; no Diversity pillar" if position == 2 else "",
            "scored": scored,
        })
    return pd.DataFrame(rows)


def write_fixture_tables(tables):
    """Write the small analysis tables needed by the fixture page."""
    pd.DataFrame({
        "income_group": ["lower-income areas", "middle-income areas", "higher-income areas"],
        "top_quintile_share": [0.10, 0.20, 0.30],
        "bottom_quintile_share": [0.30, 0.20, 0.10],
    }).to_csv(tables / "vibrancy_equity.csv", index=False)
    pd.DataFrame({"variant": ["Equal per indicator", "Intensity only"],
                  "spearman_rank_correlation": [0.95, 0.89],
                  "top_25_overlap": [17, 25]}).to_csv(tables / "vibrancy_sensitivity.csv", index=False)
    pd.DataFrame({"sa2_code": [117031329, 117031330, 117031331, 117031333, 117031336],
                  "sa2_name": ["Alpha", "Bravo", "Charlie", "Delta", "Echo"],
                  "Baseline": [1, 2, 3, 4, 5], "Equal per indicator": [1, 3, 2, 4, 5],
                  "Intensity only": [1, 2, 3, 4, 5]}).to_csv(tables / "vibrancy_variant_ranks.csv", index=False)
    pd.DataFrame({"global_morans_i": [0.5], "p_value": [0.001]}).to_csv(tables / "vibrancy_hotspot_global.csv", index=False)
    pd.DataFrame({"sa2_code": [117031329, 117031330, 117031331, 117031333, 117031336],
                  "sa2_name": ["Alpha", "Bravo", "Charlie", "Delta", "Echo"],
                  "local_i": [0.4, 0.1, 0.0, 0.2, 0.3], "p_value": [0.001, 0.25, 0.5, 0.032, 0.9],
                  "hotspot_class": ["high-high", "not significant", "not significant", "low-low", "not significant"],
                  "number_of_neighbours": [3, 4, 2, 5, 3],
                  "neighbour_average_score": [101.26, 99.94, 100.0, 98.44, 97.05]}).to_csv(tables / "vibrancy_hotspots.csv", index=False)
    pd.DataFrame({
        "place_type": ["dense and diverse", "dense and less diverse"],
        "sa2s": [2, 1], "residents": [2100, 1100],
        "best_ranked_examples": ["Alpha; Echo", "Bravo"],
    }).to_csv(tables / "vibrancy_place_types.csv", index=False)
    pd.DataFrame({"day_type": ["weekday", "weekend"], "spearman": [0.3, 0.2]}).to_csv(tables / "vibrancy_foot_traffic_check.csv", index=False)


def visible_text(page):
    """Return page text without embedded scripts, styles or tags."""
    without_blocks = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", page, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"<[^>]+>", " ", without_blocks)


def sentences_in(text):
    """Return the sentences of visible page text, with runs of spaces collapsed."""
    one_line = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return [sentence for sentence in re.split(r"(?<=[.!?]) ", one_line) if sentence]


def repeated_sentences(page):
    """Return the sentences that appear more than once in a page's visible text."""
    sentences = sentences_in(visible_text(page))
    repeated = {sentence for sentence in sentences if sentences.count(sentence) > 1}
    return sorted(repeated)


def check_page_says_things_once(page, stats):
    """Assert that no sentence repeats and that the dates and the middle-share figure appear once."""
    repeated = repeated_sentences(page)
    text = visible_text(page)
    middle_share_text = f"{stats['score_middle_share']:.0%} of SA2s"
    source_dates_once = text.count("Source dates") == 1
    middle_share_once = text.count(middle_share_text) == 1
    assert not repeated, f"Sentences repeated word for word: {repeated}"
    assert source_dates_once, f"'Source dates' appears {text.count('Source dates')} times, not once"
    assert middle_share_once, f"'{middle_share_text}' appears {text.count(middle_share_text)} times, not once"


def test_fixture_page_says_dates_and_middle_share_once_and_repeats_no_sentence(tmp_path):
    scores_path = tmp_path / "scores.csv"
    tables = tmp_path / "tables"
    tables.mkdir()
    fixture_scores().to_csv(scores_path, index=False)
    write_fixture_tables(tables)
    _, stats, _ = story_builder().build(scores_path, tmp_path / "story", tables, images=False)
    page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    check_page_says_things_once(page, stats)


def test_real_page_says_dates_and_middle_share_once_and_repeats_no_sentence(tmp_path):
    scores = ROOT / "output" / "vibrancy_scores.csv"
    if not scores.exists():
        pytest.skip("The saved score output is not available")
    _, stats, _ = story_builder().build(scores, tmp_path / "story", ROOT / "output", images=False)
    page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    check_page_says_things_once(page, stats)


def test_real_outputs_build_when_available(tmp_path):
    scores = ROOT / "output" / "vibrancy_scores.csv"
    if not scores.exists():
        pytest.skip("The saved score output is not available")
    builder = story_builder()
    _, stats, written = builder.build(scores, tmp_path / "story", ROOT / "output")
    page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    text = visible_text(page)
    has_scores = scores.stat().st_size > 0
    has_table = "Table view: 372 scored SA2s" in text
    has_placeholders = "{{" in page
    has_negative_zero = bool(re.search(r"(?<![\d.])-0\.0(?!\d)", text))
    wrote_page = any(path.name == "index.html" for path in written)
    assert has_scores, "The saved score output is empty"
    assert has_table, "The real page is missing its scored-SA2 table label"
    assert not has_placeholders, "The real page has an unresolved placeholder"
    assert not has_negative_zero, "Visible real-page text contains negative zero"
    assert wrote_page, "The real-output smoke build did not write index.html"
    assert stats["headline"]["scored_sa2s"] == 372, "The real-output smoke build did not score 372 SA2s"


def contrast_ratio(first, second):
    """Return the WCAG contrast ratio for two six-digit hex colours."""
    def luminance(value):
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    light, dark = sorted([luminance(first), luminance(second)], reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_card_percentiles_and_tints_follow_the_display_rules():
    builder = story_builder()
    values = pd.DataFrame({"residents_per_ha": [1.0, 2.0], "businesses_per_km2": [3.0, 4.0], "stops_per_km2": [5.0, 6.0], "intersections_per_km2": [7.0, 8.0]})
    row = values.iloc[1].copy()
    row["residents"] = 100
    facts = builder.card_facts(row, values)
    assert any(fact["percentile"] == "the highest of 2 SA2s" for fact in facts)
    assert all("100%" not in fact["percentile"] for fact in facts)
    for label in ["dense and diverse", "dense and less diverse"]:
        assert contrast_ratio(builder.PLACE_COLORS[label], "#fcfcfb") >= 3


def test_rank_band_summary_uses_true_quintiles_and_names_each_biggest_mover():
    builder = story_builder()
    scores = pd.DataFrame({
        "sa2_name": ["Top A", "Top B", "Second", "Middle", "Fourth", "Bottom"],
        "vibrancy_rank": [1, 75, 76, 150, 225, 299],
        "rank_min": [1, 50, 20, 100, 30, 280],
        "rank_max": [21, 80, 120, 220, 170, 320],
    })
    summary = builder.rank_band_summary(scores)
    assert [row["label"] for row in summary] == [
        "Top quintile (2 SA2s)", "Second quintile (1 SA2s)", "Middle quintile (1 SA2s)",
        "Fourth quintile (1 SA2s)", "Bottom quintile (1 SA2s)",
    ]
    assert [row["median"] for row in summary] == [25.0, 100.0, 120.0, 140.0, 40.0]
    assert [row["mover_name"] for row in summary] == ["Top B", "Second", "Middle", "Fourth", "Bottom"]
    assert summary[0]["mover_rank_min"] == 50
    assert summary[0]["mover_rank_max"] == 80


def test_z_fixture_page_has_data_driven_headline_and_rank_classes(tmp_path):
    scores = fixture_scores()
    scores_path = tmp_path / "scores.csv"
    tables = tmp_path / "tables"
    tables.mkdir()
    scores.to_csv(scores_path, index=False)
    write_fixture_tables(tables)
    builder = story_builder()
    regions, stats, written = builder.build(scores_path, tmp_path / "story", tables, images=False)
    page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    text = visible_text(page)
    expected_title = (
        f"The most vibrant quintile of Sydney's SA2s covers {stats['headline']['top_area_share']:.0%} "
        f"of the land but holds {stats['headline']['top_resident_share']:.0%} of its residents."
    )
    checks = {
        "page output": written[-1].name == "index.html",
        "headline": expected_title in text,
        "rank classes": stats["rank_counts"] == [1, 1, 1, 1, 1],
        "placeholders": "{{" not in page,
        "negative zero": not bool(re.search(r"(?<![\d.])-0\.0(?!\d)", text)),
        "forbidden word": "bustl" not in text.lower(),
        "version label": "v1" not in text.lower(),
        "em dash": "—" not in text,
        "footer": "proxy for conditions that can support street activity" in text,
        "repository name": "Bustling-score-analysis-for-Greater-Sydney" not in text,
        "colour separation": set(builder.PLACE_COLORS.values()).isdisjoint(builder.RAMP),
        "hot-spot colour": builder.HOTSPOT_COLOR not in builder.PLACE_COLORS.values(),
        "score column": 'data-sort="score"' in page,
        "score wording": "Score" in text,
        "fixture has missing income": scores["median_income"].isna().any(),
        "fixture has missing diversity": scores["diversity_score"].isna().any(),
        "place-card container": 'class="four"' in page,
        "data credit": "OpenStreetMap" in text,
        "missing date": "date not recorded" not in text,
        "type swatch": 'class="type-swatch"' in page,
        "output wording": "saved score output" not in text,
        "analysis wording": "saved analysis outputs" not in text,
        "indicator code D1": "D1" not in text,
        "indicator code G1": "G1" not in text,
    }
    for label, passed in checks.items():
        assert passed, f"Fixture page check failed: {label}"


def test_score_fifth_labels_use_data_derived_boundaries():
    builder = story_builder()
    scored = pd.DataFrame({"vibrancy_score": [80.0, 90.0, 100.0, 110.0, 120.0]})
    labels = builder.score_fifth_labels(scored)
    assert labels == [
        "Top quintile: 112.0 and above",
        "Second quintile: 104.0 to under 112.0",
        "Middle quintile: 96.0 to under 104.0",
        "Fourth quintile: 88.0 to under 96.0",
        "Bottom quintile: under 88.0",
    ]


def test_card_score_axis_clips_values_and_formats_zero_without_a_negative_sign():
    builder = story_builder()
    card = {
        "name": "Example", "place_type": "dense and diverse", "score": 100.0,
        "rank": 1, "rank_min": 1, "rank_max": 2, "facts": [], "text": "Example text.",
        "pillars": [
            {"label": "Intensity", "value": 141.0, "clipped": 130.0},
            {"label": "Diversity", "value": 0.0, "clipped": 70.0},
            {"label": "Design", "value": 69.0, "clipped": 70.0},
        ],
    }
    markup = builder.card_html(card)
    checks = {
        "axis": ">70</span><span>Greater Sydney average</span><span>130<" in markup,
        "high clamp": "<span>141.0</span><small>off scale</small>" in markup,
        "low clamp": "<span>69.0</span><small>off scale</small>" in markup,
        "no negative zero": "-0.0" not in markup,
    }
    for label, passed in checks.items():
        assert passed, f"Card score-axis check failed: {label}"


def test_saved_scores_have_standardised_display_columns():
    scores_path = ROOT / "output" / "vibrancy_scores.csv"
    if not scores_path.exists():
        pytest.skip("The saved score output is not available")
    scores = pd.read_csv(scores_path)
    scored = scores[scores["scored"]]
    columns = ["vibrancy_score", "intensity_score", "diversity_score", "design_score"]
    checks = {
        "new columns": all(column in scores.columns for column in columns),
        "overall mean": abs(scored["vibrancy_score"].mean() - 100) < 1e-12,
        "overall population SD": abs(scored["vibrancy_score"].std(ddof=0) - 10) < 1e-12,
        "excluded missing score": pd.isna(scores.loc[~scores["scored"], "vibrancy_score"]).all(),
    }
    for label, passed in checks.items():
        assert passed, f"Saved-score display check failed: {label}"


def test_interactive_fixture_has_profile_fields_layers_and_kpis(tmp_path):
    scores = fixture_scores()
    scores_path = tmp_path / "scores.csv"
    tables = tmp_path / "tables"
    tables.mkdir()
    scores.to_csv(scores_path, index=False)
    write_fixture_tables(tables)
    builder = story_builder()
    _, stats, written = builder.build(scores_path, tmp_path / "story", tables, images=False)
    page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    embedded = re.search(r'<script id="story-data" type="application/json">(.*?)</script>', page, re.DOTALL)
    assert embedded is not None, "Fixture page needs embedded data"
    data = json.loads(embedded.group(1))
    first = data["geo"]["features"][0]["properties"]
    required = {"score", "rank", "rank_min", "rank_max", "intensity", "diversity", "design", "residents", "median_income", "flag", "residents_per_ha", "businesses_per_km2", "stops_per_km2", "intersections_per_km2"}
    checks = {
        "profile fields": required.issubset(first),
        "null diversity": any(feature["properties"]["diversity"] is None for feature in data["geo"]["features"]),
        "null income": any(feature["properties"]["median_income"] is None for feature in data["geo"]["features"]),
        "layers": set(data["layers"]) == {"overall", "intensity", "diversity", "design", "place_types", "hotspots"},
        "search list": (
            'id="sa2-names"' in page and
            len(data["geo"]["features"]) >= len(scores) and
            all(feature["properties"]["name"] for feature in data["geo"]["features"])
        ),
        "layer buttons": re.findall(r'<button class="chip layer[^"\n]*" data-layer="(\w+)"', page) == [
            "overall", "intensity", "diversity", "design", "place_types", "hotspots",
        ],
        "kpis": page.count('class="kpi"') == 4,
        "headline calculation": f"{stats['headline']['top_area_share']:.1%}" in visible_text(page),
        "static figure builder": "figure_distance" in BUILDER_PATH.read_text(encoding="utf-8"),
        "negative zero": not bool(re.search(r"(?<![\d.])-0\.0(?!\d)", visible_text(page))),
    }
    for label, passed in checks.items():
        assert passed, f"Interactive fixture check failed: {label}"


def test_variant_rank_export_has_all_runs_and_valid_rank_values():
    """The sensitivity picker receives one rank for each scored SA2 and run."""
    path = ROOT / "output" / "vibrancy_variant_ranks.csv"
    if not path.exists():
        pytest.skip("The saved rank export is not available")
    ranks = pd.read_csv(path)
    rank_columns = list(ranks.columns[2:])
    checks = {
        "rows": len(ranks) == 372,
        "rank columns": len(rank_columns) == 23,
        "baseline first": rank_columns[0] == "Baseline",
        "valid ranks": all(sorted(ranks[column].astype(int)) == list(range(1, 373)) for column in rank_columns),
    }
    for label, passed in checks.items():
        assert passed, f"Variant-rank export check failed: {label}"


def fixture_weight_ranks(rows, weights):
    """Apply the page's missing-pillar weight rule to a small score fixture."""
    raw = []
    for _, row in rows.iterrows():
        values = [row["intensity_z"], row["diversity_z"], row["design_z"]]
        available = [(value, weight) for value, weight in zip(values, weights) if pd.notna(value)]
        raw.append(sum(value * weight for value, weight in available) / sum(weight for _, weight in available))
    return pd.Series(raw, index=rows.index).rank(ascending=False, method="first").astype(int)


def test_weight_fixture_reproduces_equal_intensity_and_missing_pillar_rules():
    """Equal weights preserve ranks, intensity-only follows Intensity, and missing values renormalise."""
    rows = fixture_scores().query("scored").copy()
    equal = fixture_weight_ranks(rows, [1, 1, 1])
    intensity = fixture_weight_ranks(rows, [1, 0, 0])
    expected_equal = rows["vibrancy_rank"].astype(int).tolist()
    expected_intensity = rows["intensity_z"].rank(ascending=False, method="first").astype(int).tolist()
    missing_row = rows[rows["diversity_z"].isna()].index[0]
    checks = {
        "equal ranks": equal.tolist() == expected_equal,
        "intensity ranks": intensity.tolist() == expected_intensity,
        "missing diversity": equal.loc[missing_row] == 3,
    }
    for label, passed in checks.items():
        assert passed, f"Weight-fixture check failed: {label}"


def fixture_place_card(diversity):
    """Return a place-card record whose Diversity score is the given value (NaN for a missing pillar)."""
    missing = pd.isna(diversity)
    return {
        "place_type": "dense and diverse", "name": "Fixture", "score": 100.0, "rank": 1, "rank_min": 1, "rank_max": 2,
        "pillars": [
            {"label": "Intensity", "value": 118.0, "clipped": 118.0},
            {"label": "Diversity", "value": diversity, "clipped": None if missing else max(70, min(130, diversity))},
            {"label": "Design", "value": 60.0, "clipped": 70},
        ],
        "facts": [], "text": "Fixture text.",
    }


def pillar_row(card_html, label):
    """Return the HTML of one pillar row of a place card."""
    match = re.search(rf'<div class="pillar [^"\n]+"[^>]*><span>{label}</span>(.*?)</b></div>', card_html)
    assert match is not None, f"No {label} row in the card"
    return match.group(1)


def test_place_card_shows_a_missing_pillar_as_n_a_with_no_marker_and_no_off_scale_tag():
    """A missing pillar is n/a alone; a present value below 70 keeps its marker and its off-scale tag."""
    builder = story_builder()
    card = builder.card_html(fixture_place_card(float("nan")))
    missing_row = pillar_row(card, "Diversity")
    off_scale_row = pillar_row(card, "Design")
    checks = {
        "says n/a": "<span>n/a</span>" in missing_row,
        "no marker": "<i>" not in missing_row,
        "no off-scale tag": "off scale" not in missing_row,
        "present off-scale value keeps its tag": "<small>off scale</small>" in off_scale_row,
        "present off-scale value keeps its marker": "<i>" in off_scale_row,
    }
    for label, passed in checks.items():
        assert passed, f"Missing-pillar card check failed: {label}"


def zero_fact_percentiles(zero_count, total):
    """Return the four fact descriptions for an SA2 whose four values are zero, with zero_count zeros of total."""
    builder = story_builder()
    columns = ["residents_per_ha", "businesses_per_km2", "stops_per_km2", "intersections_per_km2"]
    values = [0.0] * zero_count + [float(value) for value in range(1, total - zero_count + 1)]
    scored = pd.DataFrame({column: values for column in columns})
    row = pd.Series({**{column: 0.0 for column in columns}, "residents": 0, "area_km2": 10.0})
    return [fact["percentile"] for fact in builder.card_facts(row, scored)]


def test_zero_fact_says_how_common_zero_is_instead_of_higher_than():
    """Zero is described by how many SA2s share it: none other, under 1%, or a whole percent that rounds halves up."""
    assert set(zero_fact_percentiles(1, 200)) == {"none, as in no other SA2"}
    assert set(zero_fact_percentiles(2, 400)) == {"none, as in fewer than 1% of SA2s"}
    assert set(zero_fact_percentiles(5, 200)) == {"none, as in 3% of SA2s"}
    assert set(zero_fact_percentiles(30, 200)) == {"none, as in 15% of SA2s"}


def test_non_zero_facts_keep_the_higher_than_and_highest_wording():
    """A value above zero is still described against the other scored SA2s."""
    builder = story_builder()
    columns = ["residents_per_ha", "businesses_per_km2", "stops_per_km2", "intersections_per_km2"]
    scored = pd.DataFrame({column: [float(value) for value in range(0, 201)] for column in columns})
    middle = pd.Series({**{column: 100.0 for column in columns}, "residents": 9000})
    top = pd.Series({**{column: 200.0 for column in columns}, "residents": 9000})
    middle_facts = [fact["percentile"] for fact in builder.card_facts(middle, scored)]
    top_facts = [fact["percentile"] for fact in builder.card_facts(top, scored)]
    assert set(middle_facts) == {"higher than 50% of SA2s"}
    assert set(top_facts) == {"the highest of 201 SA2s"}


CARD_DENSITY_COLUMNS = ["residents_per_ha", "businesses_per_km2", "stops_per_km2", "intersections_per_km2"]


def small_density_facts(values, residents=100, area_km2=10.0):
    """Return (display, comparison) for each fact of an SA2 with the given densities among 200 scored SA2s.

    The other 199 SA2s have densities 1, 2, 3 ... 199, so an SA2 with a small density is below every one of them.
    """
    builder = story_builder()
    scored = pd.DataFrame({column: [float(value) for value in range(1, 200)] + [values[column]]
                           for column in CARD_DENSITY_COLUMNS})
    row = pd.Series({**values, "residents": residents, "area_km2": area_km2})
    return [(fact["display"], fact["percentile"]) for fact in builder.card_facts(row, scored)]


def test_small_residents_density_shows_the_residents_total_and_says_density_in_the_second_line():
    """0.0002 residents per hectare with 3 residents reads "3 residents in total", ranked by density (199 of 200 SA2s are above it)."""
    densities = {column: 50.0 for column in CARD_DENSITY_COLUMNS}
    densities["residents_per_ha"] = 0.0002
    display, comparison = small_density_facts(densities, residents=3)[0]
    assert display == "3 residents in total"
    assert comparison == "density lower than 99% of SA2s"


def test_one_resident_uses_the_singular_and_a_large_total_uses_a_thousands_separator():
    """"1 resident in total", and "3,593 residents in total" for a place with 0.5 to 1 residents per hectare."""
    densities = {column: 50.0 for column in CARD_DENSITY_COLUMNS}
    densities["residents_per_ha"] = 0.0002
    assert small_density_facts(densities, residents=1)[0][0] == "1 resident in total"
    densities["residents_per_ha"] = 0.7
    assert small_density_facts(densities, residents=3593)[0][0] == "3,593 residents in total"


def test_residents_density_of_one_or_more_keeps_the_per_hectare_wording_in_the_singular_for_a_displayed_one():
    """1.4 residents per hectare is not small: a whole-number density, "1 resident" in the singular, and no "density"."""
    densities = {column: 50.0 for column in CARD_DENSITY_COLUMNS}
    densities["residents_per_ha"] = 1.4
    display, comparison = small_density_facts(densities)[0]
    assert display == "1 resident per hectare"
    assert comparison == "lower than 99% of SA2s"


def test_small_intersection_and_stop_densities_show_their_whole_number_totals():
    """0.046 intersections per km² over 129.823 km² is 6 intersections; 0.7 stops per km² over 10 km² is 7 stops."""
    densities = {column: 50.0 for column in CARD_DENSITY_COLUMNS}
    densities["intersections_per_km2"] = 6 / 129.823
    intersections = small_density_facts(densities, area_km2=129.823)[3]
    assert intersections[0] == "6 street intersections in total"
    assert intersections[1] == "density lower than 99% of SA2s"
    densities = {column: 50.0 for column in CARD_DENSITY_COLUMNS}
    densities["stops_per_km2"] = 0.7
    assert small_density_facts(densities, area_km2=10.0)[2][0] == "7 stops in total"
    densities["stops_per_km2"] = 0.1
    assert small_density_facts(densities, area_km2=10.0)[2][0] == "1 stop in total"
    densities = {column: 50.0 for column in CARD_DENSITY_COLUMNS}
    densities["businesses_per_km2"] = 0.1
    assert small_density_facts(densities, area_km2=10.0)[1][0] == "1 registered business in total"


def test_a_displayed_one_takes_the_singular_on_all_four_densities_and_any_other_number_the_plural():
    """1.2 shows as 1 (singular), 1.5 rounds up to 2 (plural), and 2.0 is plural, for each of the four facts."""
    singular = ["1 resident per hectare", "1 business per km²", "1 stop per km²", "1 intersection per km²"]
    plural = ["2 residents per hectare", "2 businesses per km²", "2 stops per km²", "2 intersections per km²"]
    for value, expected in [(1.2, singular), (1.5, plural), (2.0, plural)]:
        densities = {column: value for column in CARD_DENSITY_COLUMNS}
        assert [display for display, _ in small_density_facts(densities)] == expected


def test_a_value_below_the_50th_percentile_reads_lower_than_from_the_strictly_greater_share():
    """The 50th percentile is "higher than 50%"; one below it is "lower than Y%", Y the share above it, halves up, capped at 99."""
    builder = story_builder()
    scored = pd.Series([float(value) for value in range(1, 201)])
    assert builder.density_comparison(scored, 100.0) == "higher than 50% of SA2s"
    assert builder.density_comparison(scored, 99.0) == "lower than 51% of SA2s"
    assert builder.density_comparison(scored, 150.0) == "higher than 75% of SA2s"
    assert builder.density_comparison(scored, 40.0) == "lower than 80% of SA2s"
    assert builder.density_comparison(scored, 0.5) == "lower than 99% of SA2s"
    assert builder.density_comparison(scored, 199.0) == "higher than 99% of SA2s"


def test_ties_raise_the_share_at_or_below_and_are_not_counted_as_above():
    """Half the SA2s sharing a value count as "at or below", so that value is "higher than 50%", not "lower"."""
    builder = story_builder()
    scored = pd.Series([3.0] * 100 + [5.0] * 100)
    assert builder.density_comparison(scored, 3.0) == "higher than 50% of SA2s"
    scored = pd.Series([3.0] * 60 + [5.0] * 140)
    assert builder.density_comparison(scored, 3.0) == "lower than 70% of SA2s"


def test_the_totals_form_keeps_density_in_front_and_the_per_unit_form_does_not():
    """A total is a count, so its second line says which density is compared; a density line already is one."""
    densities = {column: 50.0 for column in CARD_DENSITY_COLUMNS}
    densities["stops_per_km2"] = 0.7
    densities["intersections_per_km2"] = 3.0
    facts = small_density_facts(densities, area_km2=10.0)
    assert facts[2] == ("7 stops in total", "density lower than 99% of SA2s")
    assert facts[3] == ("3 intersections per km²", "lower than 98% of SA2s")


def test_exact_zero_gives_a_zero_total_and_keeps_the_zero_wording():
    """A density of exactly zero reads "0 ... in total" with the "none, as in ..." second line."""
    densities = {column: 0.0 for column in CARD_DENSITY_COLUMNS}
    facts = small_density_facts(densities, residents=0)
    assert [display for display, _ in facts] == [
        "0 residents in total", "0 registered businesses in total", "0 stops in total", "0 street intersections in total",
    ]
    assert {comparison for _, comparison in facts} == {"none, as in no other SA2"}


def test_a_density_times_area_that_is_not_whole_fails_loudly():
    """The saved densities are counts over area; a product that is not whole means the inputs disagree."""
    builder = story_builder()
    assert builder.total_count(6 / 129.823, 129.823) == 6
    assert builder.total_count(float("nan"), 129.823) is None
    with pytest.raises(AssertionError):
        builder.total_count(0.046, 129.823)


def script_constant(script, name):
    """Return the number declared as `const name = number;` in a script."""
    match = re.search(rf"^const {name} = (\d+(?:\.\d+)?);$", script, re.MULTILINE)
    assert match is not None, f"The template has no constant {name}"
    return float(match.group(1))


def test_template_and_builder_declare_the_same_nouns_units_and_limits_for_the_four_facts():
    """The profile card and the place cards say "resident" and "residents" the same way, and differ only in two unit words."""
    builder = story_builder()
    template = (ROOT / "scripts" / "vibrancy_story_template.html").read_text(encoding="utf-8")
    script_start = template.index("<script>", template.index('id="story-data"')) + len("<script>")
    script = template[script_start:template.index("</script>", script_start)]
    definitions = script[script.index("const factDefinitions = ["):]
    definitions = definitions[:definitions.index("];")]
    pair = r"\['([^']+)', '([^']+)'\]"
    template_units = re.findall(rf"units: {pair}", definitions)
    template_nouns = re.findall(rf"nouns: {pair}", definitions)
    assert len(template_units) == 4 and len(template_nouns) == 4
    assert template_nouns == [fact[3] for fact in builder.CARD_FACTS]
    for (template_one, template_many), fact in zip(template_units, builder.CARD_FACTS):
        builder_one, builder_many = fact[2]
        assert template_one.replace("registered ", "").replace("street ", "") == builder_one
        assert template_many.replace("registered ", "").replace("street ", "") == builder_many


def test_builder_and_template_use_the_same_small_density_limits():
    """Each limit is one named constant on each side, and the four facts use them in the same order."""
    builder = story_builder()
    template = (ROOT / "scripts" / "vibrancy_story_template.html").read_text(encoding="utf-8")
    script_start = template.index("<script>", template.index('id="story-data"')) + len("<script>")
    script = template[script_start:template.index("</script>", script_start)]
    definitions = script[script.index("const factDefinitions = ["):]
    definitions = definitions[:definitions.index("];")]
    limit_names = re.findall(r"limit: (\w+),", definitions)
    assert script_constant(script, "smallResidentsPerHa") == builder.SMALL_RESIDENTS_PER_HA
    assert script_constant(script, "smallDensityPerKm2") == builder.SMALL_DENSITY_PER_KM2
    assert limit_names == ["smallResidentsPerHa", "smallDensityPerKm2", "smallDensityPerKm2", "smallDensityPerKm2"]
    assert [fact[4] for fact in builder.CARD_FACTS] == [
        builder.SMALL_RESIDENTS_PER_HA, builder.SMALL_DENSITY_PER_KM2, builder.SMALL_DENSITY_PER_KM2, builder.SMALL_DENSITY_PER_KM2,
    ]


def fixture_map_regions(hotspot_classes=("high-high", "low-low", "high-low", "low-high")):
    """Return nine small SA2 squares: seven scored inside the built-up frame, one scored far outside it, one not scored.

    Two of the scored SA2s have no Diversity score.
    """
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import box
    hotspots = list(hotspot_classes) + ["not significant"] * (8 - len(hotspot_classes))
    rows = []
    for position in range(9):
        west = 150.2 if position == 7 else 151.0 + position * 0.03
        scored = position < 8
        rows.append({
            "sa2_code": 100 + position, "sa2_name": f"Fixture {position}", "scored": scored,
            "rank_class": float(position % 5) if scored else np.nan,
            "place_type": list(story_builder().PLACE_COLORS)[position % 4] if scored else "not scored",
            "hotspot_class": hotspots[position] if scored else "not significant",
            "vibrancy_score": 55.0 if position == 7 else 100.0 + 6 * (position - 3) if scored else np.nan,
            "neighbour_average_score": 100.0 + 3 * (position - 3) if scored else np.nan,
            "intensity_z": float(position), "design_z": float(8 - position),
            "diversity_z": np.nan if position in (2, 5) else float(position * 0.5),
            "geometry": box(west, -33.90, west + 0.025, -33.85),
        })
    return gpd.GeoDataFrame(rows, crs=4326)


def totals_match_densities(data, area_km2=10.0):
    """Return whether every SA2's stop, intersection and business totals equal its density times the fixture area."""
    pairs = [("stops", "stops_per_km2"), ("intersections", "intersections_per_km2"), ("businesses", "businesses_per_km2")]
    for feature in data["geo"]["features"]:
        properties = feature["properties"]
        for total, density in pairs:
            if properties[density] is not None and properties[total] != round(properties[density] * area_km2):
                return False
    return True


def test_builder_and_template_start_the_moran_axis_at_the_same_score():
    """The scatterplot's clip point is one named constant on each side."""
    template = (ROOT / "scripts" / "vibrancy_story_template.html").read_text(encoding="utf-8")
    match = re.search(r"^const moranAxisMinimum = (\d+);$", template, re.MULTILINE)
    assert match is not None
    assert int(match.group(1)) == story_builder().MORAN_AXIS_MINIMUM


def test_moran_figure_has_both_axis_titles_the_slope_line_and_the_clip_note(tmp_path):
    """The static scatterplot passes the layout check, names both axes, the four quadrants and the slope, and notes the clipped SA2."""
    import matplotlib
    matplotlib.use("Agg")
    builder = story_builder()
    (tmp_path / "images").mkdir()
    figures = []
    real_layout_check = builder.assert_figure_text_layout

    def layout_check_that_keeps_the_figure(figure):
        figures.append(figure)
        real_layout_check(figure)

    stats = {"global_i": 0.5, "moran": {"title": "Neighbouring SA2s tend to score alike: 1 high-high and 1 low-low clusters"}}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(builder, "assert_figure_text_layout", layout_check_that_keeps_the_figure)
        path = builder.figure_moran(fixture_map_regions(), stats, tmp_path)
    figure = figures[0]
    axis = figure.axes[0]
    texts = [text.get_text() for text in figure.findobj(matplotlib.text.Text) if text.get_text()]
    dots = sum(len(collection.get_offsets()) for collection in axis.collections)
    checks = {
        "file name": path.name == "vibrancy_moran.png" and path.exists(),
        "layout check ran once": len(figures) == 1,
        "axis titles": (axis.get_xlabel(), axis.get_ylabel()) == ("Vibrancy score", "Average score of neighbouring SA2s"),
        "quadrant labels": all(label in texts for label in ["High-high", "Low-high", "Low-low", "High-low"]),
        "slope label": "slope 0.50 (Moran's I)" in texts,
        "clip note": "1 SA2 is left of the axis: Fixture 7 (score 55.0)." in texts,
        "one SA2 is left off the plot": dots == 7,
        "axis starts at the constant": axis.get_xlim()[0] == builder.MORAN_AXIS_MINIMUM,
    }
    for label, passed in checks.items():
        assert passed, f"Moran figure check failed: {label}"


def test_moran_axis_note_names_each_clipped_sa2_and_says_nothing_when_none():
    """The note counts and names the SA2s below the axis start, with their scores, and is empty if there are none."""
    builder = story_builder()
    scored = pd.DataFrame({"sa2_name": ["Low", "Lower", "Fine"], "vibrancy_score": [58.0, 40.25, 90.0]})
    assert builder.moran_axis_note(scored) == "2 SA2s are left of the axis: Lower (score 40.2), Low (score 58.0)."
    assert builder.moran_axis_note(scored.iloc[[2]]) == ""
    assert builder.moran_axis_note(scored.iloc[[1]]) == "1 SA2 is left of the axis: Lower (score 40.2)."


def test_moran_card_text_is_built_from_the_data():
    """Counts, outlier names and the low-low shares come from the data; the caveat and the two clusters are always there."""
    builder = story_builder()
    regions = pd.DataFrame({
        "scored": [True] * 6,
        "sa2_name": ["A", "B", "C", "D", "E", "F"],
        "hotspot_class": ["high-high", "low-low", "low-low", "high-low", "low-high", "not significant"],
        "residents": [100, 10, 10, 50, 20, 10], "AREASQKM21": [1.0, 40.0, 40.0, 2.0, 3.0, 4.0],
    })
    card = builder.moran_card_text(regions, 0.5479)
    assert card["title"] == "Neighbouring SA2s tend to score alike: 1 high-high and 2 low-low clusters"
    assert card["paragraphs"][0].endswith("here it is 0.55, so nearby SA2s often score alike.")
    assert "D scores high among lower-scoring neighbours. E scores low among higher-scoring ones." in card["paragraphs"][1]
    assert card["paragraphs"][1].endswith("The other 1 are not clusters.")
    assert card["paragraphs"][2] == (
        "The 2 low-low SA2s hold 10.0% of residents but cover 88.9% of the land we scored, "
        "so the group is mostly large, sparsely populated areas."
    )
    assert card["paragraphs"][3] == "Clusters are descriptive: no correction is made for testing many areas."


def test_distance_card_title_uses_group_medians_and_a_named_outer_exception():
    """The title states the near-to-far median contrast and names the highest-scoring SA2 beyond 10 km."""
    builder = story_builder()
    regions = pd.DataFrame({
        "scored": [True] * 7,
        "sa2_name": ["Near1", "Near2", "Near3", "Far1", "Far2", "Outer high", "Outer low"],
        "distance_km": [1.0, 2.0, 3.0, 45.0, 50.0, 25.0, 30.0],
        "vibrancy_score": [110.0, 120.0, 130.0, 80.0, 90.0, 125.0, 70.0],
    })
    title = builder.distance_card_title(regions)
    assert title == (
        "The median score falls from 120.0 near the centre to 90.0 beyond 40 km, "
        "but a few centres such as Outer high buck the trend"
    )


def test_fixture_page_data_carries_cluster_names_counts_neighbour_averages_and_p_values(tmp_path):
    """The page data gets the plain class names, their counts, and each SA2's neighbours' average and local p-value."""
    scores = fixture_scores()
    scores_path = tmp_path / "scores.csv"
    tables = tmp_path / "tables"
    tables.mkdir()
    scores.to_csv(scores_path, index=False)
    write_fixture_tables(tables)
    builder = story_builder()
    builder.build(scores_path, tmp_path / "story", tables, images=False)
    page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    embedded = re.search(r'<script id="story-data" type="application/json">(.*?)</script>', page, re.DOTALL)
    data = json.loads(embedded.group(1))
    by_name = {feature["properties"]["name"]: feature["properties"] for feature in data["geo"]["features"]}
    hotspots = data["layers"]["hotspots"]
    checks = {
        "class order": data["hotspot_order"] == ["high-high", "low-low", "high-low", "low-high", "not significant"],
        "plain names": hotspots["labels"] == [builder.HOTSPOT_NAMES[name] for name in data["hotspot_order"]],
        "counts": hotspots["counts"] == [1, 0, 0, 0, 4],
        "layer name": hotspots["name"] == "Hot spots",
        "neighbour average": by_name["Alpha"]["neighbour_average_score"] == 101.3,
        "p-value": by_name["Delta"]["hotspot_p_value"] == 0.032,
        "not scored is null": by_name["Excluded"]["neighbour_average_score"] is None,
        "global I": data["global_i"] == 0.5,
    }
    for label, passed in checks.items():
        assert passed, f"Hot-spot data check failed: {label}"


def test_fixture_page_embeds_chart_and_control_data_without_static_page_images(tmp_path):
    """The page carries the data its SVG charts and what-if controls need."""
    scores = fixture_scores()
    scores_path = tmp_path / "scores.csv"
    tables = tmp_path / "tables"
    tables.mkdir()
    scores.to_csv(scores_path, index=False)
    write_fixture_tables(tables)
    builder = story_builder()
    _, _, _ = builder.build(scores_path, tmp_path / "story", tables, images=False)
    page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    embedded = re.search(r'<script id="story-data" type="application/json">(.*?)</script>', page, re.DOTALL)
    data = json.loads(embedded.group(1))
    properties = data["geo"]["features"][0]["properties"]
    image_tags = re.findall(r"<img\b[^>]*>", page, flags=re.IGNORECASE)
    checks = {
        "pillar z values": {"intensity_z", "diversity_z", "design_z"}.issubset(properties),
        "variant ranks": len(data["variant_ranks"]) == 5 and "Baseline" in data["variant_ranks"][0],
        "sensitivity": len(data["sensitivity"]) == 2,
        "chart controls": all(token in page for token in ["distance-chart", "histogram-chart", "what-if", "variant-picker"]),
        "no page images": len(image_tags) == 0,
        "null safe": any(feature["properties"]["diversity"] is None for feature in data["geo"]["features"]),
        "whole-number totals": totals_match_densities(data),
    }
    for label, passed in checks.items():
        assert passed, f"Interactive chart fixture check failed: {label}"


# The ten static figures in the order the builder writes them, and the axis titles of the five chart figures.
STATIC_FIGURES = [
    "vibrancy_map.png", "vibrancy_intensity_map.png", "vibrancy_diversity_map.png", "vibrancy_design_map.png",
    "vibrancy_place_types.png", "vibrancy_hotspots.png", "vibrancy_moran.png", "vibrancy_equity.png",
    "vibrancy_rank_ranges.png", "vibrancy_foot_traffic_weekday.png", "vibrancy_foot_traffic_weekend.png",
    "vibrancy_distance.png",
]
CHART_FIGURE_AXIS_TITLES = [
    ("Vibrancy score", "Average score of neighbouring SA2s"),
    ("Median income group", "Share of residents (%)"),
    ("Median movement in rank across 22 variants", "Baseline rank quintile"),
    ("Vibrancy score", "Weekday average walking count"),
    ("Vibrancy score", "Weekend average walking count"),
    ("Distance from the Sydney GPO (km)", "Vibrancy score"),
]


def test_real_story_build_keeps_static_figures_but_page_does_not_reference_them(tmp_path, monkeypatch):
    """Ten named figures are written, each passes the text-layout check, and the page shows none of them."""
    scores = ROOT / "output" / "vibrancy_scores.csv"
    if not scores.exists():
        pytest.skip("The saved score output is not available")
    builder = story_builder()
    axis_titles_seen = []
    real_layout_check = builder.assert_figure_text_layout

    def layout_check_that_records_axis_titles(figure):
        axis_titles_seen.append([(axis.get_xlabel(), axis.get_ylabel()) for axis in figure.axes])
        real_layout_check(figure)

    monkeypatch.setattr(builder, "assert_figure_text_layout", layout_check_that_records_axis_titles)
    _, _, written = builder.build(scores, tmp_path / "story", ROOT / "output")
    page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    image_paths = [path for path in written if path.suffix == ".png"]
    image_tags = re.findall(r"<img\b[^>]*>", page, flags=re.IGNORECASE)
    chart_titles = [titles[0] for titles in axis_titles_seen if titles[0] != ("", "")]
    checks = {
        "figure file names": [path.name for path in image_paths] == STATIC_FIGURES,
        "figure files written": all(path.exists() for path in image_paths),
        "layout check on every figure": len(axis_titles_seen) == len(STATIC_FIGURES),
        "titles on both axes of every chart": chart_titles == CHART_FIGURE_AXIS_TITLES,
        "no static page images": len(image_tags) == 0,
    }
    for label, passed in checks.items():
        assert passed, f"Static-figure check failed: {label}"


def test_limits_and_methods_are_data_driven_and_visible(tmp_path):
    """Keep the five limits and the methods summary present in a fixture page."""
    scores = fixture_scores()
    scores_path = tmp_path / "scores.csv"
    tables = tmp_path / "tables"
    tables.mkdir()
    scores.to_csv(scores_path, index=False)
    write_fixture_tables(tables)
    builder = story_builder()
    _, stats, _ = builder.build(scores_path, tmp_path / "story", tables, images=False)
    page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    text = visible_text(page)
    limits_match = re.search(r'<ul id="limits-list"[^>]*>(.*?)</ul>', page, re.DOTALL)
    items = re.findall(r"<li>(.*?)</li>", limits_match.group(1)) if limits_match else []
    checks = {
        "limits element": limits_match is not None,
        "five limits": len(items) == 5,
        "computed limits": all(item in text for item in stats["limits"]),
        "airport business count": "registered businesses" in items[3] if len(items) == 5 else False,
        "methods pillars": all(name in text for name in ["Intensity", "Diversity", "Design"]),
        "no visible z score": "z-score" not in text.lower(),
        "no visible negative zero": not bool(re.search(r"(?<![\d.])-0\.0(?!\d)", text)),
    }
    for label, passed in checks.items():
        assert passed, f"Limits and methods check failed: {label}"


def test_headline_sentence_uses_the_top_quintiles_shares():
    builder = story_builder()
    headline = {"top_area_share": 0.021, "top_resident_share": 0.223}
    assert builder.headline_sentence(headline) == (
        "The most vibrant quintile of Sydney's SA2s covers 2% of the land but holds 22% of its residents."
    )


def test_place_type_split_counts_and_title_read_the_two_dense_rows():
    builder = story_builder()
    place_types = pd.DataFrame({
        "place_type": ["dense and diverse", "dense and less diverse", "less dense and diverse"],
        "sa2s": [117, 101, 79],
    })
    counts = builder.place_type_split_counts(place_types)
    assert counts == (117, 101)
    assert builder.place_type_split_title(*counts) == (
        "Dense places split in two: 117 have a varied business mix and 101 do not"
    )


def test_equity_income_shares_and_title_compare_the_two_named_income_groups():
    builder = story_builder()
    equity = pd.DataFrame({
        "income_group": ["lower-income areas", "middle-income areas", "higher-income areas"],
        "top_quintile_share": [0.16, 0.20, 0.32],
    })
    high, low = builder.equity_income_shares(equity)
    assert (high, low) == (32.0, 16.0)
    assert builder.equity_card_title(high, low) == (
        "Residents of higher-income areas are about twice as likely to live in a "
        "top-quintile SA2 (32% against 16%)"
    )


def test_foot_traffic_spearman_and_title_read_one_days_row():
    builder = story_builder()
    foot = pd.DataFrame({"day_type": ["weekday", "weekend"], "spearman": [0.42, 0.31]})
    assert builder.foot_traffic_spearman(foot, "weekday") == 0.42
    assert builder.foot_traffic_day_title(foot, "weekday") == "Busier weekdays track a higher score too (Spearman 0.42)"
    assert builder.foot_traffic_day_title(foot, "weekend") == "Busier weekends track a higher score too (Spearman 0.31)"


def test_distance_outer_exceptions_match_the_example_named_by_distance_card_title():
    """The static figure and distance_card_title must always name the same SA2s, from one shared rule."""
    builder = story_builder()
    regions = pd.DataFrame({
        "scored": [True] * 6,
        "sa2_name": ["Near", "Mid low", "Mid high", "Mid lower", "Outer high", "Far low"],
        "distance_km": [2.0, 12.0, 15.0, 20.0, 30.0, 45.0],
        "vibrancy_score": [110.0, 95.0, 105.0, 90.0, 130.0, 80.0],
    })
    scored = regions[regions["scored"] == True]
    exceptions = builder.distance_outer_exceptions(scored)
    assert list(exceptions["sa2_name"]) == ["Outer high", "Mid high", "Mid low"]
    assert builder.distance_card_title(regions) == (
        "The median score falls from 110.0 near the centre to 80.0 beyond 40 km, "
        "but a few centres such as Outer high buck the trend"
    )


def test_reused_titles_are_computed_once_and_shown_identically_on_the_page_and_in_the_figures(tmp_path):
    """D26: the main map, the place-type map, the equity chart and the two foot-traffic charts each reuse a
    sentence the page already computes once in compute_stats, so the static PNG and the page can never drift."""
    import matplotlib
    matplotlib.use("Agg")
    scores_path = tmp_path / "scores.csv"
    tables = tmp_path / "tables"
    tables.mkdir()
    fixture_scores().to_csv(scores_path, index=False)
    write_fixture_tables(tables)
    # write_fixture_tables() leaves out the per-site walking-count table (no existing test draws the
    # foot-traffic figures from it), so this test adds a small one of its own.
    pd.DataFrame({
        "sa2_code": [117031329, 117031330, 117031331],
        "sa2_name": ["Alpha", "Bravo", "Charlie"],
        "weekday_average": [9000, 5000, 2000], "weekend_average": [7000, 4000, 1500],
    }).to_csv(tables / "vibrancy_foot_traffic_sa2.csv", index=False)
    builder = story_builder()
    regions = builder.add_hotspot_columns(builder.load_regions(scores_path), tables)
    stats = builder.compute_stats(regions, tables)
    page = builder.page_html(regions, stats)
    text = visible_text(page)

    figures = {}
    real_layout_check = builder.assert_figure_text_layout

    def capture(figure):
        figures[id(figure)] = figure
        real_layout_check(figure)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(builder, "assert_figure_text_layout", capture)
        (tmp_path / "images").mkdir()
        builder.figure_main_map(regions, stats, tmp_path)
        builder.figure_place_types(regions, stats, tmp_path)
        builder.figure_equity(stats, tmp_path)
        builder.figure_foot_traffic(regions, stats, tables, tmp_path)

    def all_text(figure):
        return " ".join(t.get_text() for t in figure.findobj(matplotlib.text.Text) if t.get_text())

    rendered = list(figures.values())
    checks = {
        "headline shown on the page": stats["headline_title"] in text,
        "headline shown on the main map": any(stats["headline_title"] in all_text(f) for f in rendered),
        "place-type split shown on the page": stats["place_type_title"] in text,
        "place-type split shown on its map": any(stats["place_type_title"] in all_text(f) for f in rendered),
        "equity title shown on the page": stats["equity_title"] in text,
        "equity title shown on its chart": any(stats["equity_title"] in all_text(f) for f in rendered),
        "weekday foot-traffic title shown on the page": stats["foot_titles"]["weekday"] in text,
        "weekday title shown on its chart": any(stats["foot_titles"]["weekday"] in all_text(f) for f in rendered),
        "weekend foot-traffic title shown on the page": stats["foot_titles"]["weekend"] in text,
        "weekend title shown on its chart": any(stats["foot_titles"]["weekend"] in all_text(f) for f in rendered),
    }
    for label, passed in checks.items():
        assert passed, f"Reused-title parity check failed: {label}"


