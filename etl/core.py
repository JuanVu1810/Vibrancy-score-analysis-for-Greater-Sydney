"""Shared plumbing for the ETL: paths, the manifest, snapshots and small helpers."""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
STAGING = ROOT / "staging"
MANIFEST_PATH = RAW / "manifest.json"

SRID = 4326

# Bounding boxes (minx, miny, maxx, maxy, degrees) for sanity checks. NSW reaches east to Lord Howe Island.
NSW_BBOX = (140.0, -38.0, 160.0, -27.0)
AU_BBOX = (112.0, -45.0, 160.0, -9.0)
# Greater Sydney with a margin of about 3 km, for reading only the Sydney part of large OpenStreetMap layers.
SYDNEY_BBOX = (149.9, -34.4, 151.7, -32.9)


class EtlError(Exception):
    """A source could not be read, parsed or validated."""


class NotDownloaded(EtlError):
    """A source's files are not in raw/ yet. Run download_data.py to fetch them."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_zip(path: Path) -> Path:
    """Unzip `path` into a folder next to it named after it, and return that folder.

    raw/<source>/<date>/name.zip becomes raw/<source>/<date>/name/. Zips inside it are unzipped too, each
    into a folder beside it. An earlier extraction of the same zip is reused. A file in the zip that would
    land outside the folder (a path with "..") is refused. The zip itself is kept, so its checksum can
    still be checked.
    """
    dest = path.with_suffix("")
    stamp = f"{path.stat().st_size}:{int(path.stat().st_mtime)}"
    marker = dest / ".unzipped"
    if marker.exists() and marker.read_text() == stamp:
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    root = dest.resolve()
    with zipfile.ZipFile(path) as z:
        for member in z.infolist():
            target = (root / member.filename).resolve()
            if root != target and root not in target.parents:
                raise EtlError(f"{path.name}: refusing to unzip {member.filename!r}, which would land outside {dest.name}/")
        z.extractall(dest)
    for inner in sorted(dest.rglob("*.zip")):
        extract_zip(inner)
    marker.write_text(stamp)
    return dest


def rel(path: Path) -> str:
    """Path relative to the project root, with forward slashes, so a manifest works on any machine."""
    return path.resolve().relative_to(ROOT).as_posix()


# ---------------------------------------------------------------------------------------------
# Value helpers shared by the parsers
# ---------------------------------------------------------------------------------------------
_MISSING = {"", "np", "na", "n/a", "nan", "none", "null", "-", "--", ".."}


def to_int(value):
    """Integer from an ABS/CSV cell ('2,467', 2467.0, 'np' ...); None when it isn't a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return None if value != value else int(round(value))
    s = str(value).strip().replace(",", "")
    if s.lower() in _MISSING:
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def inside(bounds, box) -> bool:
    """True when (minx, miny, maxx, maxy) `bounds` lies wholly within `box`."""
    minx, miny, maxx, maxy = bounds
    return box[0] < minx and maxx < box[2] and box[1] < miny and maxy < box[3]


def is_sa2_code(value) -> bool:
    s = str(value).strip() if value is not None else ""
    return s.isdigit() and len(s) == 9


# ---------------------------------------------------------------------------------------------
# Issues: what a source's check() returns
# ---------------------------------------------------------------------------------------------
def error(msg: str) -> tuple:
    return ("error", msg)


def warn(msg: str) -> tuple:
    return ("warn", msg)


# ---------------------------------------------------------------------------------------------
# Manifest and snapshots
# ---------------------------------------------------------------------------------------------
class Manifest:
    """raw/manifest.json: what was downloaded, from where, when, and its checksum."""

    def __init__(self, path: Path = MANIFEST_PATH):
        self.path = path
        self.data = {"schema": 1, "sources": {}}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, source_id: str):
        return self.data["sources"].get(source_id)

    def put(self, source_id: str, record: dict) -> None:
        self.data["sources"][source_id] = record

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)


@dataclass
class Snapshot:
    """The raw files one source was built from. A parser may refine `release` and `extra`."""
    source_id: str
    release: str
    url: str
    files: dict = field(default_factory=dict)  # logical name -> file record, as written by download_data.py
    extra: dict = field(default_factory=dict)
    retrieved_at: str = field(default_factory=utc_now)

    def path(self, name: str = "main") -> Path:
        return ROOT / self.files[name]["path"]

    def unzip(self, name: str = "main") -> Path:
        """The folder a zip file was unzipped into (unzipping it first if that hasn't been done)."""
        folder = extract_zip(self.path(name))
        self.extra.setdefault("unzipped_to", {})[name] = rel(folder)
        return folder

    def to_record(self) -> dict:
        return {"release": self.release, "url": self.url, "retrieved_at": self.retrieved_at,
                "files": self.files, "extra": self.extra}

    @classmethod
    def from_record(cls, source_id: str, record: dict) -> "Snapshot":
        """Rebuild a snapshot from the manifest, checking every file is there and intact."""
        snap = cls(source_id, record["release"], record["url"], record["files"],
                   record.get("extra", {}), record["retrieved_at"])
        for name, f in snap.files.items():
            p = ROOT / f["path"]
            if not p.exists():
                raise NotDownloaded(f"{source_id}: {f['path']} is missing. Run  python download_data.py {source_id}")
            if sha256_file(p) != f["sha256"]:
                raise EtlError(f"{source_id}: {f['path']} does not match its recorded checksum")
        return snap


@dataclass
class Source:
    """One raw source. `parse` turns its downloaded files into tables, and `check` validates them."""
    id: str
    title: str
    licence: str
    attribution: str
    outputs: tuple
    parse: Callable
    check: Callable


# ---------------------------------------------------------------------------------------------
# Context: the manifest, and the tables and quality records produced so far in this run
# ---------------------------------------------------------------------------------------------
class Ctx:
    def __init__(self, manifest: Manifest | None = None, verbose: bool = True):
        self.manifest = manifest or Manifest()
        self.frames: dict = {}  # tables produced in this run, for cross-source checks
        self.quality: list = []  # QualityRecords from this run (see etl/quality.py)
        self.verbose = verbose

    def log(self, msg: str) -> None:
        if self.verbose:
            print(msg, flush=True)
