"""Quality records for the ETL, in the style of the CPI forecast project's validation module.

Every check produces a QualityRecord with a status of PASS, WARNING or FAIL. A run keeps all of its
records, writes them to staging/data_quality_report.csv and to the v2.data_quality_results table, and
a FAIL stops that source from being written or loaded.

Two layers of checks feed the records:
  * the built-in checks in each source module (row counts, joins to the SA2 boundaries, coordinates),
    one record per source, named after the source;
  * the pandera schemas in etl/schemas.py (columns, types, allowed values, ranges), one record per
    table, named "pandera:<table>".
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# The columns that identify a row in each table, used to count duplicates.
KEYS = {
    "sa2_boundaries": ["SA2_CODE21"],
    "businesses": ["industry_code", "SA2_CODE21"],
    "income": ["SA2_CODE21"],
    "population": ["SA2_CODE21"],
    "schools": [],  # a school can appear more than once (primary and secondary, or two future polygons)
    "hospitals": ["topoid"],
    "polling_places": ["polling_place_id"],
    "stops": ["stop_id"],
    "traffic_lights": ["equipment_id"],
    "public_amenities": ["osm_id"],
    "crossings": ["osm_id"],
}


@dataclass(frozen=True)
class QualityRecord:
    """A compact validation result suitable for a CSV quality report."""

    dataset: str
    status: str
    rows: int
    columns: int
    missing_values: int
    duplicate_keys: int
    notes: str

    def as_dict(self) -> dict:
        return {"dataset": self.dataset, "status": self.status, "rows": self.rows, "columns": self.columns,
                "missing_values": self.missing_values, "duplicate_keys": self.duplicate_keys, "notes": self.notes}


def counts(name: str, frame) -> tuple:
    """(rows, columns, empty cells, duplicate keys) of one table."""
    key = [k for k in KEYS.get(name, []) if k in frame.columns]
    dupes = int(frame.duplicated(key).sum()) if key else 0
    return len(frame), len(frame.columns), int(frame.isna().sum().sum()), dupes


def record_from_issues(dataset: str, frames: dict, issues: list) -> QualityRecord:
    """Turn a source's built-in issues, a list of ("error"|"warn", message), into one record."""
    totals = [counts(name, frame) for name, frame in frames.items()]
    status = "FAIL" if any(level == "error" for level, _ in issues) else "WARNING" if issues else "PASS"
    return QualityRecord(dataset, status, sum(t[0] for t in totals), sum(t[1] for t in totals),
                         sum(t[2] for t in totals), sum(t[3] for t in totals),
                         "; ".join(message for _, message in issues) or "ok")


def records_to_frame(records: list) -> pd.DataFrame:
    return pd.DataFrame([r.as_dict() for r in records])


def assess(source, out: dict, ctx) -> list:
    """All quality records for one source's tables: its built-in checks, then a pandera check per table."""
    from . import schemas  # imported here so that this module stays light

    records = [record_from_issues(source.id, out, source.check(out, ctx))]
    records += [schemas.validate_table(name, frame) for name, frame in out.items()]
    return records
