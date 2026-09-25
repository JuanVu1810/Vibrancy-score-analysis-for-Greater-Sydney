"""Tests for unzipping the zip files the sources deliver."""
import io
import os
import time
import zipfile

import pytest

from etl.core import EtlError, Snapshot, extract_zip


def make_zip(path, files: dict):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)


def test_a_zip_is_unzipped_into_a_folder_beside_it_and_kept(tmp_path):
    zip_path = tmp_path / "boundaries.zip"
    make_zip(zip_path, {"a.shp": "shape", "notes/readme.txt": "hello"})
    folder = extract_zip(zip_path)
    assert folder == tmp_path / "boundaries"
    assert (folder / "a.shp").read_text() == "shape"
    assert (folder / "notes" / "readme.txt").read_text() == "hello"
    assert zip_path.exists()


def test_an_earlier_extraction_of_the_same_zip_is_reused(tmp_path):
    zip_path = tmp_path / "gtfs.zip"
    make_zip(zip_path, {"stops.txt": "stop_id\n1\n"})
    folder = extract_zip(zip_path)
    (folder / "stops.txt").write_text("edited")  # a change we would notice if the folder were rebuilt
    assert extract_zip(zip_path) == folder
    assert (folder / "stops.txt").read_text() == "edited"


def test_a_changed_zip_is_unzipped_again(tmp_path):
    zip_path = tmp_path / "gtfs.zip"
    make_zip(zip_path, {"stops.txt": "old"})
    folder = extract_zip(zip_path)
    make_zip(zip_path, {"stops.txt": "new, and longer than before"})
    os.utime(zip_path, (time.time() + 5, time.time() + 5))
    extract_zip(zip_path)
    assert (folder / "stops.txt").read_text() == "new, and longer than before"


def test_a_zip_inside_a_zip_is_unzipped_too(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("stops.txt", "stop_id\n7\n")
    outer = tmp_path / "bundle.zip"
    make_zip(outer, {"buses.zip": inner.getvalue(), "agency.txt": "x"})
    folder = extract_zip(outer)
    assert (folder / "buses" / "stops.txt").read_text() == "stop_id\n7\n"


def test_a_file_that_would_land_outside_the_folder_is_refused(tmp_path):
    zip_path = tmp_path / "bad.zip"
    make_zip(zip_path, {"../evil.txt": "no"})
    with pytest.raises(EtlError, match="outside"):
        extract_zip(zip_path)
    assert not (tmp_path / "evil.txt").exists()


def test_a_snapshot_unzips_its_file_and_records_where(tmp_path, monkeypatch):
    monkeypatch.setattr("etl.core.ROOT", tmp_path)
    make_zip(tmp_path / "catchments.zip", {"catchments_primary.shp": "x"})
    snap = Snapshot("catchments", "r", "u", {"main": {"path": "catchments.zip"}})
    folder = snap.unzip()
    assert (folder / "catchments_primary.shp").exists()
    assert snap.extra["unzipped_to"]["main"] == "catchments"
