"""Compare a fresh run (output/bustling_scores.csv) with the original results.

Two levels of comparison:
  * expected/summary.json           - always used: row count, correlation with median
                                       income, and the top 5 / bottom 5 regions.
  * expected/bustling_scores.csv    - optional: a full export of the original
                                       bustling_scores table. If present, every
                                       region and numeric column is compared.

Exit code 0 if everything matches, 1 otherwise.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "output" / "bustling_scores.csv"
SUMMARY = ROOT / "expected" / "summary.json"
FULL = ROOT / "expected" / "bustling_scores.csv"

SUMMARY_TOL = 1e-6  # summary values were recorded to 6 decimals
FULL_RTOL, FULL_ATOL = 1e-6, 1e-6

failures = []


def check(ok, label, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


if not RESULT.exists():
    sys.exit(f"{RESULT} not found - the notebook did not finish (or has not been run).")

got = pd.read_csv(RESULT).sort_values("bustling_score", ascending=False).reset_index(drop=True)
exp = json.loads(SUMMARY.read_text())

print("Checking against expected/summary.json")
check(len(got) == exp["n_scored_regions"], "number of scored regions",
      f"got {len(got)}, expected {exp['n_scored_regions']}")

corr = got["bustling_score"].corr(got["median_income"])
check(abs(corr - exp["correlation_bustling_vs_median_income"]) < SUMMARY_TOL,
      "correlation of bustling score with median income",
      f"got {corr:.6f}, expected {exp['correlation_bustling_vs_median_income']:.6f}")

for label, expected_rows, actual_rows in (("top 5", exp["top5"], got.head(5)),
                                          ("bottom 5", exp["bottom5"], got.tail(5))):
    for want, (_, have) in zip(expected_rows, actual_rows.iterrows()):
        ok = (int(have["SA2_CODE21"]) == want["SA2_CODE21"]
              and abs(have["bustling_score"] - want["bustling_score"]) < SUMMARY_TOL)
        check(ok, f"{label}: {want['SA2_NAME21']}",
              f"got {have['SA2_NAME21']} {have['bustling_score']:.6f}, expected {want['bustling_score']:.6f}")

if FULL.exists():
    print("\nChecking against expected/bustling_scores.csv (full table)")
    ref = pd.read_csv(FULL).drop(columns=["geom"], errors="ignore").set_index("SA2_CODE21").sort_index()
    new = got.drop(columns=["geom"], errors="ignore").set_index("SA2_CODE21").sort_index()
    check(set(ref.index) == set(new.index), "same set of SA2 regions",
          f"reference {len(ref)}, new {len(new)}, "
          f"only in reference {len(set(ref.index) - set(new.index))}, "
          f"only in new {len(set(new.index) - set(ref.index))}")
    common_idx = ref.index.intersection(new.index)
    common_cols = [c for c in ref.columns if c in new.columns and pd.api.types.is_numeric_dtype(ref[c])]
    missing = [c for c in ref.columns if c not in new.columns]
    check(not missing, "no columns missing from the new run", ", ".join(missing))
    worst = 0.0
    for c in common_cols:
        a, b = ref.loc[common_idx, c], new.loc[common_idx, c]
        same = np.isclose(a, b, rtol=FULL_RTOL, atol=FULL_ATOL, equal_nan=True)
        worst = max(worst, float(np.nanmax(np.abs(a - b))) if len(a) else 0.0)
        check(bool(same.all()), f"column {c}", "" if same.all() else f"{int((~same).sum())} rows differ")
    print(f"  largest absolute difference across all numeric columns: {worst:.3g}")
else:
    print("\n(expected/bustling_scores.csv not present - only the summary was checked.)")

print()
if failures:
    print(f"RESULT: {len(failures)} check(s) FAILED")
    sys.exit(1)
print("RESULT: all checks passed - the run reproduces the original results")
