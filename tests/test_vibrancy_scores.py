"""Checks on the saved score tables: the score scale, the 372 scored SA2s and the variant ranks."""

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


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
