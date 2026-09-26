"""The correlation between the bustling score and median income, with a bootstrap interval and a permutation test.

Reads expected/bustling_scores.csv (the original results) and uses only numpy and pandas.
The resampling uses a fixed seed, so you get the same numbers every time.

    python scripts/income_correlation.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESAMPLES = 10_000
SEED = 2024

df = pd.read_csv(ROOT / "expected" / "bustling_scores.csv")[["bustling_score", "median_income"]].dropna()
score, income = df.bustling_score.to_numpy(), df.median_income.to_numpy()
n = len(df)
rng = np.random.default_rng(SEED)


def pearson(a, b):
    """Pearson correlation along the last axis, so it works on one pair or on many at once."""
    a = a - a.mean(axis=-1, keepdims=True)
    b = b - b.mean(axis=-1, keepdims=True)
    return (a * b).sum(-1) / np.sqrt((a * a).sum(-1) * (b * b).sum(-1))


def ranks(values):
    """Average ranks (ties share a rank). Spearman is just Pearson on the ranks."""
    return pd.DataFrame(values).rank(axis=1).to_numpy() if values.ndim == 2 else pd.Series(values).rank().to_numpy()


observed = {"Pearson": pearson(score, income), "Spearman": pearson(ranks(score), ranks(income))}

# Bootstrap: resample the regions with replacement and recompute the correlation each time.
pick = rng.integers(0, n, size=(RESAMPLES, n))
boot = {"Pearson": pearson(score[pick], income[pick]),
        "Spearman": pearson(ranks(score[pick]), ranks(income[pick]))}

# Permutation test: shuffle income across regions to see how often chance alone does as well.
shuffled = np.array([rng.permutation(income) for _ in range(RESAMPLES)])
null = {"Pearson": pearson(np.broadcast_to(score, shuffled.shape), shuffled),
        "Spearman": pearson(np.broadcast_to(ranks(score), shuffled.shape), ranks(shuffled))}

print(f"{n} regions with a median income, {RESAMPLES:,} resamples, seed {SEED}\n")
for name in ("Pearson", "Spearman"):
    r = observed[name]
    low, high = np.percentile(boot[name], [2.5, 97.5])
    p = (np.sum(np.abs(null[name]) >= abs(r)) + 1) / (RESAMPLES + 1)
    print(f"{name:9s} r = {r:.3f} | 95% bootstrap interval {low:.2f} to {high:.2f} | permutation p = {p:.3f}")
print(f"\nr squared for Pearson: {observed['Pearson'] ** 2:.3f}")

# The same five groups as the "Score by median income" figure (scripts/build_story.py, INCOME_GROUPS)
groups = pd.qcut(df.median_income, 5, labels=["Lowest 20%", "Lower middle", "Middle", "Upper middle", "Highest 20%"])
print("\nScore by median income group:")
print(df.groupby(groups, observed=True).agg(
    income_from=("median_income", "min"), income_to=("median_income", "max"),
    regions=("bustling_score", "count"), average=("bustling_score", "mean"), median=("bustling_score", "median"),
    lowest=("bustling_score", "min"), highest=("bustling_score", "max")).round(3).to_string())
