"""Tests for reading a source back from raw/manifest.json: the checksum and the missing-file checks."""
import pytest

from etl.core import EtlError, NotDownloaded, Snapshot, sha256_file


def record_for(path):
    return {"release": "r", "url": "u", "retrieved_at": "2026-09-25T00:00:00Z",
            "files": {"main": {"path": path.name, "sha256": sha256_file(path)}}}


def test_a_file_that_matches_its_checksum_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr("etl.core.ROOT", tmp_path)
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    snap = Snapshot.from_record("demo", record_for(tmp_path / "data.csv"))
    assert snap.path() == tmp_path / "data.csv"


def test_a_file_that_changed_since_it_was_downloaded_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr("etl.core.ROOT", tmp_path)
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    record = record_for(tmp_path / "data.csv")
    (tmp_path / "data.csv").write_text("a,b\n1,3\n")  # one character different
    with pytest.raises(EtlError, match="checksum"):
        Snapshot.from_record("demo", record)


def test_a_file_that_is_not_in_raw_is_reported_as_not_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr("etl.core.ROOT", tmp_path)
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    record = record_for(tmp_path / "data.csv")
    (tmp_path / "data.csv").unlink()
    with pytest.raises(NotDownloaded, match="download_data.py"):
        Snapshot.from_record("demo", record)
