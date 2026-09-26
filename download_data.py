"""Download every source dataset into raw/. That is all it does: no cleaning, no checks, no database.

    python download_data.py                # every source that isn't in raw/ yet
    python download_data.py osm_nsw        # only the sources you name

In Docker (this also passes TFNSW_API_KEY from .env on, which the GTFS download uses):
    docker compose run --rm --no-deps --user "$(id -u):$(id -g)" --entrypoint python etl download_data.py

Each file goes to raw/<source>/<date>/<file>. A source that is already downloaded is skipped, and a file you saved
there by hand is used as it is. An unfinished download stays as <file>.part and carries on from there next time.
Every source is recorded in raw/manifest.json, so `python -m etl run` can check, clean and load the files later.

The links below are the releases on offer on 26 Sep 2026. Change a link to get a newer release.
"""
import hashlib
import http.client
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
MANIFEST = RAW / "manifest.json"
HEADERS = {"User-Agent": "vibrancy-index-downloader/1.0", "Accept-Encoding": "identity"}  # identity: bytes on the wire = the file


def link(url, filename, headers=None):
    return (url, filename, headers or {})


def layer(service, layer_id=0, fields="*"):
    """A map service layer as GeoJSON (WGS84). It is read live, page by page, by download_arcgis().
    (The Data hub's ready-made download files can be out of date: the trees one lacked 2,715 trees.)"""
    return f"{service}/{layer_id}/query?" + urlencode({"where": "1=1", "outFields": fields, "outSR": 4326, "f": "geojson",
                                                       "orderByFields": "OBJECTID", "resultRecordCount": 1000})


ABS = "https://www.abs.gov.au"
ASGS = (f"{ABS}/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/"
        "jul2021-jun2026/access-and-downloads")
HOSPITALS = layer("https://portal.spatial.nsw.gov.au/server/rest/services/NSW_FOI_Health_Facilities/MapServer", 1,
                  "topoid,generalname,alternativelabel,classsubtype,operationalstatus")
COS = "https://services1.arcgis.com/cNVyNtjGVZybOQWZ/arcgis/rest/services"  # City of Sydney

# The TfNSW website answers 403 to scripts on some networks. The API (with your key) does not.
# Without a key, or if the site blocks you, save the file from the page by hand (see the note at the top).
API_KEY = os.environ.get("TFNSW_API_KEY", "").strip()
GTFS = (link("https://api.transport.nsw.gov.au/v1/publictransport/timetables/complete/gtfs", "complete_gtfs.zip",
             {"Authorization": f"apikey {API_KEY}", "Accept": "application/octet-stream"}) if API_KEY else
        link("https://opendata.transport.nsw.gov.au/data/dataset/d1f68d4f-b778-44df-9823-cf2fa922e47f/resource/"
             "67974f14-01bf-47b7-bfa5-c7f2f8a950ca/download/full_greater_sydney_gtfs_static_0.zip",
             "full_greater_sydney_gtfs_static_0.zip"))

# source id: (what it is, {file role: link}). The ids are the ETL's, so the ETL can find the files afterwards.
SOURCES = {
    "asgs_sa2": ("SA2 boundaries, ASGS Edition 3 (2021)", {
        "main": link(f"{ASGS}/digital-boundary-files/SA2_2021_AUST_SHP_GDA2020.zip", "SA2_2021_AUST_SHP_GDA2020.zip")}),
    "abs_business": ("Counts of Australian Businesses, June 2025", {
        "main": link(f"{ABS}/statistics/economy/business-indicators/counts-australian-businesses-including-entries-and-"
                     "exits/jul2021-jun2025/8165DC09.xlsx", "8165DC09.xlsx")}),
    "abs_income": ("Personal Income in Australia, 2022-23", {
        "main": link(f"{ABS}/statistics/labour/earnings-and-working-conditions/personal-income-australia/2022-23/"
                     "Table%201%20-%20Total%20income%2C%20earners%20and%20summary%20statistics%20by%20geography%2C"
                     "%202018-19%20to%202022-23.xlsx", "personal_income_table1.xlsx")}),
    "abs_population": ("Regional population by age and sex, 30 June 2025", {
        "main": link(f"{ABS}/statistics/people/population/regional-population-age-and-sex/2025/32350DS0001_2025.xlsx",
                     "32350DS0001_2025.xlsx")}),
    "abs_mesh_blocks": ("Census 2021 mesh block counts, and the mesh block allocation file", {
        "counts": link(f"{ABS}/census/guide-census-data/mesh-block-counts/2021/Mesh%20Block%20Counts%2C%202021.xlsx",
                       "mesh_block_counts_2021.xlsx"),
        "allocation": link(f"{ASGS}/allocation-files/MB_2021_AUST.xlsx", "MB_2021_AUST.xlsx")}),
    "catchments": ("NSW school intake zones (catchments)", {
        "main": link("https://data.nsw.gov.au/data/dataset/8b1e8161-7252-43d9-81ed-6311569cb1d7/resource/"
                     "32d6f502-ddb1-45d9-b114-5e34ddfd33ac/download/catchments.zip", "catchments.zip")}),
    "hospitals": ("NSW health facilities (live service)", {"main": link(HOSPITALS, "hospitals.geojson")}),
    # City of Sydney open data (CC BY 4.0). It covers only the inner city, about 5 x 8 km, so these three are extras
    # for that area, not Greater Sydney layers. The ETL reads these files (etl/sources/cityofsydney.py).
    "cos_trees": ("City of Sydney trees", {"main": link(layer(f"{COS}/Trees/FeatureServer"), "trees.geojson")}),
    "cos_stairs": ("City of Sydney stairs", {"main": link(layer(f"{COS}/Stairs/FeatureServer"), "stairs.geojson")}),
    "cos_mobility_parking": ("City of Sydney mobility parking", {
        "main": link(layer(f"{COS}/Mobility_parking/FeatureServer", 1), "mobility_parking.geojson")}),
    # Measured pedestrian counts, kept to check the index against: 120 survey sites in 16 SA2s of the inner city, with
    # the daily average count for each March and October survey since October 2013 (the latest is March 2026).
    # It is only downloaded: the ETL has no source for it. (The same publisher's "Automatic hourly pedestrian count"
    # has just 4 counters, all in the CBD, and stops in July 2025, so it cannot be compared across SA2s.)
    "cos_walking_counts": ("City of Sydney walking count sites and survey averages", {
        "main": link(layer(f"{COS}/Walking_count_sites_summary/FeatureServer"), "walking_count_sites.geojson")}),
    "polling_places": ("AEC 2025 federal election polling places", {
        "main": link("https://results.aec.gov.au/31496/Website/Downloads/GeneralPollingPlacesDownload-31496.csv",
                     "GeneralPollingPlacesDownload-31496.csv")}),
    "gtfs_stops": ("TfNSW Timetables Complete GTFS", {"main": GTFS}),
    "traffic_lights": ("TfNSW Traffic Lights Location, June 2026", {
        "main": link("https://opendata.transport.nsw.gov.au/data/dataset/93ba5c23-f46c-45d7-98ed-96022b7ea626/resource/"
                     "406ac670-b3ad-4474-9284-c03d444a1aec/download/traffic-lights-location-data-june-2026.xlsx",
                     "traffic-lights-location-data-june-2026.xlsx")}),
    # A dated file, not "-latest", so a half-finished download can only ever be continued with the same file.
    "osm_nsw": ("OpenStreetMap, New South Wales (Geofabrik extract of 1 Sep 2026)", {
        "main": link("https://download.geofabrik.de/australia-oceania/australia/new-south-wales-260901.osm.pbf",
                     "new-south-wales-260901.osm.pbf")}),
}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url, dest, headers):
    """Save `url` as `dest`, by way of dest.part. After a dropped connection, carry on from where it stopped."""
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 11):
        have = part.stat().st_size if part.exists() else 0
        request = Request(url, headers={**HEADERS, **headers, **({"Range": f"bytes={have}-"} if have else {})})
        try:
            with urlopen(request, timeout=60) as r:
                if r.status == 206:  # the server continues from byte `have`
                    total = int(r.headers["Content-Range"].split("/")[-1])
                else:  # a normal answer: the whole file, so start the .part again
                    have, total = 0, int(r.headers.get("Content-Length") or 0)
                meta = {"final_url": r.url.split("?")[0], "etag": r.headers.get("ETag"), "last_modified": r.headers.get("Last-Modified")}
                got, shown = have, (have * 20 // total if total else 0)
                with open(part, "ab" if have else "wb") as f:
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if total > 2e7 and got * 20 // total > shown:  # a line for every 5% of a big file
                            shown = got * 20 // total
                            print(f"  {dest.name}: {shown * 5}%", flush=True)
            if total and part.stat().st_size != total:  # a cut-off connection can look like a normal end
                raise IOError(f"got {part.stat().st_size:,} of {total:,} bytes")
            if dest.suffix in (".zip", ".xlsx") and not zipfile.is_zipfile(part):
                part.unlink()
                raise IOError("not a complete zip file")
            break
        except HTTPError as e:
            if e.code == 416:  # we asked for bytes past the end, so the .part is stale: start again
                part.unlink(missing_ok=True)
                continue
            if e.code < 500:  # 403, 404 ...: trying again won't help
                raise RuntimeError(f"{url} answered {e.code}") from None
            problem = e
        except (OSError, http.client.HTTPException) as e:  # dropped connection, timeout, cut-off download
            problem = e
        print(f"  {dest.name}: {problem}; trying again ({attempt}/10)", flush=True)
        time.sleep(3)
    else:
        raise RuntimeError(f"{dest.name}: still failing after 10 attempts")
    part.replace(dest)
    return meta


def download_arcgis(url, dest):
    """Save a map service layer (see layer()) as one GeoJSON file. The service sends at most one page at a time."""
    features = []
    while True:
        for attempt in range(1, 6):
            try:
                with urlopen(Request(f"{url}&resultOffset={len(features)}", headers=HEADERS), timeout=120) as r:
                    page = json.load(r)
                break
            except (OSError, http.client.HTTPException, ValueError) as e:  # ValueError: a cut-off, unreadable page
                print(f"  {dest.name}: {e}; trying again ({attempt}/5)", flush=True)
                time.sleep(3)
        else:
            raise RuntimeError(f"{dest.name}: the service kept failing")
        if "error" in page:
            raise RuntimeError(f"{dest.name}: the service answered {page['error']}")
        features += page["features"]
        print(f"  {dest.name}: {len(features):,} features", flush=True)
        if not (page.get("exceededTransferLimit") or page.get("properties", {}).get("exceededTransferLimit")):
            break
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    return {"final_url": url.split("?")[0]}


def get_file(source, spec):
    """One file of a source, as a manifest record: use the copy already in raw/<source>/, else download it."""
    url, filename, headers = spec
    found = sorted((RAW / source).glob(f"*/{filename}"))
    if found:
        dest, meta = found[-1], {}
        print(f"  {filename}: using {dest.relative_to(ROOT)}")
    else:
        dest = RAW / source / datetime.now(timezone.utc).strftime("%Y-%m-%d") / filename
        print(f"  {filename}: downloading", flush=True)
        meta = download_arcgis(url, dest) if "/query?" in url else download(url, dest, headers)
    return {"path": str(dest.relative_to(ROOT)), "url": url, **meta, "bytes": dest.stat().st_size,
            "sha256": sha256(dest), "retrieved_at": now()}


def main(names):
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        sys.exit(f"unknown source(s): {', '.join(unknown)}. The sources are: {', '.join(SOURCES)}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"schema": 1, "sources": {}}
    failed = []
    for name in names or SOURCES:
        title, files = SOURCES[name]
        done = manifest["sources"].get(name)
        if done and all((ROOT / f["path"]).exists() for f in done["files"].values()):
            print(f"{name}: already downloaded")
            continue
        print(f"{name}: {title}", flush=True)
        try:
            manifest["sources"][name] = {
                "release": title, "url": next(iter(files.values()))[0], "retrieved_at": now(), "extra": {},
                "files": {role: get_file(name, spec) for role, spec in files.items()}}
            RAW.mkdir(exist_ok=True)
            MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except Exception as e:
            failed.append(name)
            print(f"  FAILED: {e}")
            saved_as = " and ".join(spec[1] for spec in files.values())
            print(f"  If the site blocks scripts, save it in your browser as raw/{name}/<any date>/{saved_as} and run this again.")
    print(f"\n{len(failed)} failed: {', '.join(failed)}" if failed else "\nDone.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
