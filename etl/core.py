"""Shared plumbing for the ETL: paths, the manifest, cached downloads and small helpers."""
from __future__ import annotations

import hashlib
import json
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
STAGING = ROOT / "staging"
MANUAL = RAW / "manual"
MANIFEST_PATH = RAW / "manifest.json"

SRID = 4326
USER_AGENT = ("bustling-score-etl/2.0 (+https://github.com/JuanVu1810/"
              "Bustling-score-analysis-for-Greater-Sydney)")
PARSER_VERSION = "1"  # bump when a parser's output changes, so old manifests are recognisable

# Bounding boxes (minx, miny, maxx, maxy, degrees) for sanity checks. NSW reaches east to Lord Howe Island.
NSW_BBOX = (140.0, -38.0, 160.0, -27.0)
AU_BBOX = (112.0, -45.0, 160.0, -9.0)


class EtlError(Exception):
    """A source could not be fetched, parsed or validated."""


class _Incomplete(Exception):
    """A download finished but the file is short or damaged; the caller retries."""


class MissingCredential(EtlError):
    """A source needs a credential, or a hand-downloaded file, that isn't there yet."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
def environment() -> dict:
    """Python and package versions for the manifest, like the CPI forecast project's download manifest."""
    import importlib.metadata as md
    import sys

    def version(pkg):
        try:
            return md.version(pkg)
        except md.PackageNotFoundError:
            return "not installed"
    return {"downloaded_at_utc": utc_now(), "python_version": sys.version,
            "packages": {p: version(p) for p in ("pandas", "geopandas", "pyogrio", "shapely", "openpyxl",
                                                 "requests", "pandera")}}


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
    files: dict = field(default_factory=dict)  # logical name -> file record (see Ctx.download)
    extra: dict = field(default_factory=dict)
    retrieved_at: str = field(default_factory=utc_now)

    def path(self, name: str = "main") -> Path:
        return ROOT / self.files[name]["path"]

    def to_record(self) -> dict:
        return {"release": self.release, "url": self.url, "retrieved_at": self.retrieved_at,
                "files": self.files, "extra": self.extra}

    @classmethod
    def from_record(cls, source_id: str, record: dict) -> "Snapshot":
        """Rebuild a snapshot from the manifest (pinned mode), checking every file is intact."""
        snap = cls(source_id, record["release"], record["url"], record["files"],
                   record.get("extra", {}), record["retrieved_at"])
        for name, f in snap.files.items():
            p = ROOT / f["path"]
            if not p.exists():
                raise EtlError(f"{source_id}: pinned file {f['path']} is missing (run in latest mode first)")
            if sha256_file(p) != f["sha256"]:
                raise EtlError(f"{source_id}: {f['path']} does not match its recorded checksum")
        return snap


@dataclass
class Source:
    """One raw source. `fetch` downloads it, `parse` turns it into tables, `check` validates them."""
    id: str
    title: str
    licence: str
    attribution: str
    outputs: tuple
    fetch: Callable
    parse: Callable
    check: Callable


# ---------------------------------------------------------------------------------------------
# Context: HTTP session, cached downloads and the frames produced so far in this run
# ---------------------------------------------------------------------------------------------
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=5, connect=5, read=3, backoff_factor=1.5,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET", "HEAD"))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


class Ctx:
    def __init__(self, mode: str = "latest", refresh: bool = False, manifest: Manifest | None = None,
                 verbose: bool = True):
        self.mode = mode
        self.refresh = refresh
        self.manifest = manifest or Manifest()
        self.session = make_session()
        self.today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.frames: dict = {}  # tables produced in this run, for cross-source checks
        self.quality: list = []  # QualityRecords from this run (see etl/quality.py)
        self.verbose = verbose

    def log(self, msg: str) -> None:
        if self.verbose:
            print(msg, flush=True)

    # -- HTTP -------------------------------------------------------------------------------
    def get(self, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", 60)
        return self.session.get(url, **kw)

    def _unchanged(self, prev: dict, url: str, headers) -> bool:
        """True when the server says the file is the one we already have (ETag or date and size)."""
        try:
            r = self.session.head(url, headers=headers, allow_redirects=True, timeout=30)
        except requests.RequestException:
            return False
        if r.status_code != 200:
            return False
        etag, mod, size = r.headers.get("ETag"), r.headers.get("Last-Modified"), r.headers.get("Content-Length")
        if etag and prev.get("etag"):
            return etag == prev["etag"]
        return bool(mod and prev.get("last_modified") and mod == prev["last_modified"]
                    and size and str(prev["bytes"]) == size)

    def fetch_to(self, url: str, dest: Path, headers: dict | None = None, attempts: int = 4) -> dict:
        """Stream `url` into `dest` and return its checksum, size and server details.

        Some servers (ABS in particular) cut a transfer short now and then, so an interrupted or
        incomplete download is retried. Zip and Excel files are also checked to be readable zips.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        for attempt in range(1, attempts + 1):
            try:
                with self.session.get(url, headers=headers, stream=True, timeout=(15, 120)) as r:
                    if r.status_code in (401, 403):
                        raise EtlError(f"{url} answered {r.status_code} (access denied; check the "
                                       f"credential, or download the file by hand)")
                    r.raise_for_status()
                    h, size = hashlib.sha256(), 0
                    with open(part, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                            h.update(chunk)
                            size += len(chunk)
                    expected = r.headers.get("Content-Length")
                    if (expected and expected.isdigit() and int(expected) != size
                            and not r.headers.get("Content-Encoding")):
                        raise _Incomplete(f"got {size} of {expected} bytes")
                    if dest.suffix.lower() in (".zip", ".xlsx", ".xlsm") and not zipfile.is_zipfile(part):
                        raise _Incomplete("the file is not a complete zip")
                    meta = {"sha256": h.hexdigest(), "bytes": size, "final_url": r.url,
                            "etag": r.headers.get("ETag"), "last_modified": r.headers.get("Last-Modified")}
                part.replace(dest)
                return meta
            except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout, _Incomplete) as e:
                part.unlink(missing_ok=True)
                if attempt == attempts:
                    raise EtlError(f"{dest.name}: download kept failing ({type(e).__name__}: {e})") from e
                self.log(f"  {dest.name}: interrupted ({type(e).__name__}), trying again ({attempt}/{attempts - 1})")
                time.sleep(2 * attempt)
        raise AssertionError("unreachable")

    def download(self, source_id: str, name: str, url: str, filename: str | None = None,
                 headers: dict | None = None) -> dict:
        """Download `url` into raw/<source>/<date>/ (or reuse the previous copy if unchanged).

        `headers` may carry credentials; they are sent but never written to the manifest.
        """
        filename = filename or Path(urlsplit(url).path).name or name
        prev = ((self.manifest.get(source_id) or {}).get("files") or {}).get(name)
        if prev and not self.refresh and (ROOT / prev["path"]).exists() and self._unchanged(prev, url, headers):
            self.log(f"  {source_id}: {filename} unchanged, reusing {prev['path']}")
            return dict(prev)

        dest = RAW / source_id / self.today / filename
        if not self.refresh and dest.exists() and dest.stat().st_size > 0 and (
                dest.suffix.lower() not in (".zip", ".xlsx", ".xlsm") or zipfile.is_zipfile(dest)):
            # fetched earlier today (for example a run that failed its checks): no need to download it again
            self.log(f"  {source_id}: {filename} was already downloaded today, reusing it (use --refresh to force)")
            when = datetime.fromtimestamp(dest.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return {"path": rel(dest), "url": url, "final_url": None, "sha256": sha256_file(dest),
                    "bytes": dest.stat().st_size, "etag": None, "last_modified": None, "retrieved_at": when}
        self.log(f"  {source_id}: downloading {filename}")
        try:
            meta = self.fetch_to(url, dest, headers)
        except EtlError as e:
            raise EtlError(f"{source_id}: {e}") from None
        self.log(f"  {source_id}: {filename} ({meta['bytes'] / 1e6:.1f} MB)")
        return {"path": rel(dest), "url": url, "final_url": meta["final_url"], "sha256": meta["sha256"],
                "bytes": meta["bytes"], "etag": meta["etag"], "last_modified": meta["last_modified"],
                "retrieved_at": utc_now()}

    def store(self, source_id: str, name: str, filename: str, data: bytes, url: str) -> dict:
        """Save bytes we built ourselves (for example a paged API response) as a raw file."""
        dest_dir = RAW / source_id / self.today
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        dest.write_bytes(data)
        return {"path": rel(dest), "url": url, "final_url": url, "sha256": sha256_file(dest),
                "bytes": len(data), "etag": None, "last_modified": None, "retrieved_at": utc_now()}

    def adopt(self, source_id: str, name: str, src: Path) -> dict:
        """Copy a hand-downloaded file into raw/<source>/<date>/ and record its checksum."""
        dest_dir = RAW / source_id / self.today
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if not dest.exists() or sha256_file(dest) != sha256_file(src):
            dest.write_bytes(src.read_bytes())
        return {"path": rel(dest), "url": f"manual:{rel(src)}", "final_url": None,
                "sha256": sha256_file(dest), "bytes": dest.stat().st_size, "etag": None,
                "last_modified": None, "retrieved_at": utc_now()}
