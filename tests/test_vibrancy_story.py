"""Checks for the local Greater Sydney story-page build."""

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

    The five scored rows sample each rank quintile; the sixth row has no score.
    """
    names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Excluded"]
    place_types = [
        "dense and diverse", "dense and less diverse", "less dense and diverse",
        "less dense and less diverse", "dense and diverse", "",
    ]
    ranks = [1, 76, 150, 225, 299, None]
    minimum_ranks = [1, 50, 100, 175, 250, None]
    maximum_ranks = [150, 175, 240, 310, 372, None]
    rows = []
    for position, name in enumerate(names):
        scored = position < 5
        rank = ranks[position]
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
            "diversity_score": None if position == 2 else (105 - position * 4 if scored else None),
            "design_score": 112 - position * 6 if scored else None,
            "vibrancy_rank": rank if scored else None,
            "vibrancy_quintile": 5 - position if scored else None,
            "place_type": place_types[position],
            "hotspot_class": "high-high" if position == 0 else "not significant",
            "rank_min": minimum_ranks[position],
            "rank_max": maximum_ranks[position],
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
    pd.DataFrame({"sa2_code": [117031329, 117031330, 117031331, 117031333, 124021456],
                  "sa2_name": ["Alpha", "Bravo", "Charlie", "Delta", "Echo"],
                  "Baseline": [1, 76, 150, 225, 299], "Equal per indicator": [1, 80, 145, 230, 299],
                  "Intensity only": [1, 76, 150, 225, 299]}).to_csv(tables / "vibrancy_variant_ranks.csv", index=False)
    pd.DataFrame({"global_morans_i": [0.5], "p_value": [0.001]}).to_csv(tables / "vibrancy_hotspot_global.csv", index=False)
    pd.DataFrame({"sa2_code": [117031329, 117031330, 117031331, 117031333, 124021456],
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
    """Return the visible page text without scripts, styles or tags."""
    page = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", page, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"<[^>]+>", " ", page)


def build_fixture(tmp_path, images=False):
    """Build the story from six small SA2 rows and saved chart tables."""
    scores_path = tmp_path / "scores.csv"
    tables = tmp_path / "tables"
    tables.mkdir()
    fixture_scores().to_csv(scores_path, index=False)
    write_fixture_tables(tables)
    builder = story_builder()
    regions, stats, written = builder.build(scores_path, tmp_path / "story", tables, images=images)
    page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    return builder, regions, stats, written, page


def embedded_data(page):
    """Read the data that powers the map and charts in the built page."""
    match = re.search(r'<script id="story-data" type="application/json">(.*?)</script>', page, re.DOTALL)
    assert match is not None, "The story page needs embedded data"
    return json.loads(match.group(1))


def test_fixture_builds_page_and_seven_figures(tmp_path):
    builder, regions, stats, written, page = build_fixture(tmp_path, images=True)
    figure_names = [path.name for path in written if path.suffix == ".png"]
    assert figure_names == [
        "vibrancy_map.png", "vibrancy_intensity_map.png", "vibrancy_diversity_map.png",
        "vibrancy_design_map.png", "vibrancy_place_types.png", "vibrancy_equity.png",
        "vibrancy_rank_ranges.png",
    ]
    assert all(path.exists() for path in written)
    assert written[-1].name == "index.html"
    assert stats["rank_counts"] == [1, 1, 1, 1, 1]
    assert "{{" not in page
    assert "<img" not in page.lower(), "The page draws charts instead of using the PNGs"
    assert not re.search(r"(?<![\d.])-0\.0(?!\d)", visible_text(page))


def test_fixture_page_carries_the_interactive_results(tmp_path):
    builder, regions, stats, written, page = build_fixture(tmp_path)
    data = embedded_data(page)
    by_name = {feature["properties"]["name"]: feature["properties"] for feature in data["geo"]["features"]}
    profile_fields = {
        "score", "rank", "rank_min", "rank_max", "intensity", "diversity", "design",
        "residents", "median_income", "businesses", "stops", "intersections", "flag",
    }
    assert profile_fields.issubset(by_name["Alpha"])
    assert by_name["Bravo"]["median_income"] is None
    assert by_name["Charlie"]["diversity"] is None
    assert by_name["Alpha"]["businesses"] == 100
    assert by_name["Alpha"]["stops"] == 20
    assert set(data["layers"]) == {"overall", "intensity", "diversity", "design", "place_types", "hotspots"}
    assert data["layers"]["hotspots"]["counts"] == [1, 0, 0, 0, 4]
    assert len(data["variant_ranks"]) == 5
    assert "Baseline" in data["variant_ranks"][0]
    assert len(data["sensitivity"]) == 2
    assert all(token in page for token in ["distance-chart", "histogram-chart", "what-if", "variant-picker"])
    assert page.count('class="kpi"') == 4


def test_fixture_page_states_the_result_and_limits(tmp_path):
    builder, regions, stats, written, page = build_fixture(tmp_path)
    text = visible_text(page)
    headline = builder.headline_sentence(stats["headline"])
    assert headline in text
    assert "Source dates" in text
    assert "Intensity" in text and "Diversity" in text and "Design" in text
    assert all(limit in text for limit in stats["limits"])
    assert "proxy for conditions that can support street activity" in text


def test_score_fifths_follow_the_data():
    builder = story_builder()
    scored = pd.DataFrame({"vibrancy_score": [80, 90, 100, 110, 120]})
    assert builder.score_fifth_labels(scored) == [
        "Top quintile: 112.0 and above",
        "Second quintile: 104.0 to under 112.0",
        "Middle quintile: 96.0 to under 104.0",
        "Fourth quintile: 88.0 to under 96.0",
        "Bottom quintile: under 88.0",
    ]


def test_rank_bands_use_actual_rank_ranges():
    builder = story_builder()
    scores = pd.DataFrame({
        "sa2_name": ["Top A", "Top B", "Second", "Middle", "Fourth", "Bottom"],
        "vibrancy_rank": [1, 75, 76, 150, 225, 299],
        "rank_min": [1, 50, 20, 100, 30, 280],
        "rank_max": [21, 80, 120, 220, 170, 320],
    })
    bands = builder.rank_band_summary(scores)
    assert [band["median"] for band in bands] == [25, 100, 120, 140, 40]
    assert [band["mover_name"] for band in bands] == ["Top B", "Second", "Middle", "Fourth", "Bottom"]


def test_place_card_shows_a_missing_pillar_plainly():
    builder = story_builder()
    card = {
        "name": "Example", "place_type": "dense and diverse", "score": 100.0,
        "rank": 1, "rank_min": 1, "rank_max": 2, "facts": [], "text": "Example text.",
        "pillars": [
            {"label": "Intensity", "value": 118.0, "clipped": 118.0},
            {"label": "Diversity", "value": float("nan"), "clipped": None},
            {"label": "Design", "value": 69.0, "clipped": 70.0},
        ],
    }
    markup = builder.card_html(card)
    assert "<span>n/a</span>" in markup
    assert "<span>69.0</span><small>off scale</small>" in markup
    assert "-0.0" not in markup


def test_card_facts_show_whole_totals_for_small_densities():
    builder = story_builder()
    row = pd.Series({
        "area_km2": 10.0, "residents": 2, "residents_per_ha": 0.002,
        "businesses_per_km2": 0.2, "stops_per_km2": 0.0,
        "intersections_per_km2": 0.5,
    })
    scored = pd.DataFrame({
        "residents_per_ha": [0.002, 1.0, 2.0],
        "businesses_per_km2": [0.2, 1.0, 2.0],
        "stops_per_km2": [0.0, 1.0, 2.0],
        "intersections_per_km2": [0.5, 1.0, 2.0],
    })
    facts = builder.card_facts(row, scored)
    assert [fact["display"] for fact in facts] == [
        "2 residents in total", "2 registered businesses in total",
        "0 stops in total", "5 street intersections in total",
    ]
    assert facts[2]["percentile"] == "none, as in no other SA2"


def test_saved_scores_and_variant_ranks_when_available():
    scores_path = ROOT / "output" / "vibrancy_scores.csv"
    ranks_path = ROOT / "output" / "vibrancy_variant_ranks.csv"
    if not scores_path.exists() or not ranks_path.exists():
        pytest.skip("The saved analysis outputs are not available")
    scores = pd.read_csv(scores_path)
    scored = scores[scores["scored"]]
    ranks = pd.read_csv(ranks_path)
    assert len(scores) == 373 and len(scored) == 372
    assert abs(scored["vibrancy_score"].mean() - 100) < 1e-12
    assert abs(scored["vibrancy_score"].std(ddof=0) - 10) < 1e-12
    assert scores.loc[~scores["scored"], "vibrancy_score"].isna().all()
    assert len(ranks) == 372
    assert len(ranks.columns[2:]) == 23
    assert ranks.columns[2] == "Baseline"
    assert sorted(ranks["Baseline"].astype(int)) == list(range(1, 373))


def test_real_outputs_build_when_available(tmp_path):
    scores = ROOT / "output" / "vibrancy_scores.csv"
    if not scores.exists():
        pytest.skip("The saved score output is not available")
    _, stats, written = story_builder().build(scores, tmp_path / "story", ROOT / "output", images=False)
    page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    assert stats["headline"]["scored_sa2s"] == 372
    assert "Table view: 372 scored SA2s" in visible_text(page)
    assert "{{" not in page
    assert written[-1].name == "index.html"
