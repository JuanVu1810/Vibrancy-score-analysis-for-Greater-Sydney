"""Checks on the saved hot-spot tables: the neighbours' average and the identities behind the page's Moran scatterplot."""

import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
HOTSPOT_COLUMNS = [
    "sa2_code", "sa2_name", "local_i", "p_value", "hotspot_class", "number_of_neighbours", "neighbour_average_score",
]
CLASS_COUNTS = {"high-high": 35, "low-low": 47, "high-low": 2, "low-high": 1, "not significant": 287}


def read_rows(filename):
    """Read one saved output table as a list of dictionaries."""
    path = OUTPUT / filename
    if not path.exists():
        pytest.skip(f"{filename} is not available")
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def hotspot_rows_with_scores():
    """Return the hot-spot rows with the SA2's own vibrancy score added."""
    scores = {row["sa2_code"]: float(row["vibrancy_score"]) for row in read_rows("vibrancy_scores.csv") if row["scored"] == "True"}
    rows = read_rows("vibrancy_hotspots.csv")
    return [{**row, "score": scores[row["sa2_code"]]} for row in rows]


def test_hotspot_table_keeps_its_columns_and_adds_the_neighbours_average_last():
    """The neighbours' average is the last column, after the columns that were already there."""
    rows = read_rows("vibrancy_hotspots.csv")
    assert list(rows[0]) == HOTSPOT_COLUMNS
    assert len(rows) == 372


def test_class_counts_are_the_agreed_ones():
    """The clusters are 35 high-high, 47 low-low, 2 high-low, 1 low-high and 287 not significant."""
    rows = read_rows("vibrancy_hotspots.csv")
    counts = {name: sum(1 for row in rows if row["hotspot_class"] == name) for name in CLASS_COUNTS}
    assert counts == CLASS_COUNTS


def test_local_statistic_is_the_standardised_score_times_the_neighbours_standardised_average():
    """Scores are 100 + 10 times a standardised value, so local I = ((score - 100) / 10) * ((average - 100) / 10)."""
    rows = hotspot_rows_with_scores()
    errors = []
    for row in rows:
        own = (row["score"] - 100) / 10
        neighbours = (float(row["neighbour_average_score"]) - 100) / 10
        errors.append(abs(float(row["local_i"]) - own * neighbours))
    assert max(errors) < 1e-9, f"Largest difference from the identity: {max(errors)}"


def test_mean_of_the_local_statistics_is_the_global_morans_i():
    """The global statistic is the mean of the local ones, which is why the scatterplot line can have slope I."""
    rows = read_rows("vibrancy_hotspots.csv")
    global_i = float(read_rows("vibrancy_hotspot_global.csv")[0]["global_morans_i"])
    mean_local = sum(float(row["local_i"]) for row in rows) / len(rows)
    assert abs(mean_local - global_i) < 1e-9


def test_slope_through_100_100_recomputed_from_the_two_columns_equals_the_global_morans_i():
    """The least-squares line through (100, 100) of the neighbours' average on the score has slope Moran's I."""
    rows = hotspot_rows_with_scores()
    across = sum((row["score"] - 100) * (float(row["neighbour_average_score"]) - 100) for row in rows)
    along = sum((row["score"] - 100) ** 2 for row in rows)
    global_i = float(read_rows("vibrancy_hotspot_global.csv")[0]["global_morans_i"])
    assert abs(across / along - global_i) < 1e-9
    assert f"{across / along:.3f}" == "0.548"
