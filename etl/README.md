# ETL for the Greater Sydney bustling score

This downloads every source dataset, cleans it into a consistent shape, checks it, and loads it into
PostGIS. It's the v2 way of getting data: the v1 files in `data/` were handed out with an assignment
and their original publishers weren't recorded, so nothing could be refreshed. Here every source has
a documented publisher, a licence, and a record of exactly which release was used.

It never touches `data/`, the notebook, or the v1 tables in the `public` schema. Cleaned tables go to
`staging/` (files) and to a new `v2` schema in the database.

## Quick start

```bash
cp .env.example .env          # first time only; skip if you already have one
# put your private DB_PASSWORD in .env, and your TfNSW key too (see below)
docker compose build etl      # first time, and whenever requirements.lock changes
docker compose run --rm etl   # fetch everything, check it, load it into schema v2
```

The other commands:

```bash
docker compose run --rm etl list                       # sources and the tables they make
docker compose run --rm etl run --only abs_business    # just one source
docker compose run --rm --no-deps etl run --no-db      # files in staging/ only, no database
docker compose run --rm --no-deps etl run --mode pinned   # reuse the exact files in raw/manifest.json, no network
docker compose run --rm --no-deps etl verify           # check the staged tables (built-in checks and pandera)
docker compose run --rm --no-deps etl verify --parity  # also test the parsers against the v1 files (downloads about 10 MB)
```

Run it in Docker: the pinned geospatial libraries aren't installed on a plain host Python. Without
Docker, `python -m etl ...` works in an environment built from `requirements.lock`.

## Transport for NSW (stops and traffic lights)

The TfNSW Open Data Hub refused scripted downloads for hours on 25 Sep 2026 (a CDN block that answered
403 to everything, even its home page) and then stopped. So each TfNSW source tries its routes in order
and only stops if all of them fail:

| Source | 1st choice | 2nd | 3rd |
|---|---|---|---|
| GTFS stops | The API, if `TFNSW_API_KEY` is set | The public download link, found through the portal catalogue | A zip saved in `raw/manual/gtfs/` |
| Traffic lights | The file listed in the Data.NSW catalogue | A file saved in `raw/manual/traffic_lights/` | |

The API key is free: register at <https://opendata.transport.nsw.gov.au>, create an application, and add
`TFNSW_API_KEY=...` to your private **`.env`**. It's sent as `Authorization: apikey <key>` and is never
written to the manifest. **Don't put it in `.env.example`**: that file is tracked by git and would be
committed. A source that can't be fetched reports `NOT RUN` with instructions, and the others carry on.

## What it produces

| Table (schema v2) | Source | Publisher | Notes |
|---|---|---|---|
| `sa2_boundaries` | ASGS Edition 3 SA2 (2021) | ABS | Greater Sydney only (373 SA2s) |
| `businesses` | Counts of Australian Businesses, data cube 9 | ABS | NSW, industries A to S; industry X (unknown) dropped |
| `income` | Personal Income in Australia, Table 1 (total income) | ABS | NSW SA2s, newest year in the workbook |
| `population` | Regional population by age and sex | ABS | Greater Sydney SA2s, persons, five-year bands |
| `stops` | Timetables Complete GTFS, `stops.txt` | TfNSW | Blank `location_type` becomes 0 (a stop); 1 is a station. A few rows with typo coordinates keep an empty geometry |
| `polling_places` | 2025 federal election polling places | AEC | NSW; places without coordinates kept with an empty geometry |
| `schools` | School intake zones (catchments) | NSW Dept of Education | Future catchments replace current ones, as in v1 |
| `traffic_lights` | Traffic Lights Location | TfNSW | `asset_type` is `Vehicle` or `Pedestrian` in every release (v1's VEH/PED are mapped to these); rows with typo coordinates keep an empty geometry |
| `hospitals` | NSW Features of Interest, Health Facilities | NSW Spatial Services | Includes private hospitals and a few ACT ones |
| `public_amenities`, `crossings` | OpenStreetMap, Geofabrik NSW extract | OpenStreetMap contributors (ODbL) | Mapped points only, like v1; `crossings.is_zebra` matches v1's zebra-only file |

Table names and key columns (`SA2_CODE21`, `USE_ID`, and so on) match the v1 tables, so the scoring
SQL can be pointed at schema `v2` with few changes. New tables use lower-case `snake_case` columns.
`v2.etl_manifest` lists, for every source, the release, URL, retrieval time and licence, and each
table carries a `COMMENT` with the same.

## Where the v1 files came from

The v1 README says the publisher of several files wasn't recorded. Matching their numbers against ABS
releases traced three of them exactly, and `verify --parity` re-checks this every time:

| v1 file | Matches exactly | Rows |
|---|---|---|
| `data/Businesses.csv` | ABS Counts of Australian Businesses, June 2022 (Jul 2018 to Jun 2022 release), data cube 9 | 12,217 |
| `data/Income.csv` | ABS Personal Income in Australia, 2020-21 release, Table 1.4 (total income, 2020-21 column) | 642 |
| `data/Population.csv` | ABS Regional population by age and sex, 2021 release (30 June 2021 estimates), persons | 373 |

Two more dates are recorded inside the v1 files themselves: `public_amenities.geojson` and
`crossings.geojson` carry OpenStreetMap timestamps of 13 and 14 May 2024, and the catchments say
enrolment year 2023. So the v1 inputs range from 2020-21 income to 2024 OpenStreetMap data.

## How "latest" works

In `latest` mode each source works out the newest release itself:

- **ABS pages** are read for the current download links. Businesses steps back through earlier
  releases if the newest one hasn't published its SA2 cubes yet (they arrive months after the headline
  numbers).
- **Data.NSW** is asked for the current catchments URL through its catalogue.
- **AEC** uses a fixed election id in `etl/sources/aec.py` (`EVENT_ID`). Change it after the next federal election.
- **Geofabrik** and the **TfNSW API** always serve the current file.

Downloads land in `raw/<source>/<date>/`. If the server says a file hasn't changed since the last
run (ETag, or date and size), the old copy is reused. `raw/manifest.json` records URL, retrieval time,
size and SHA-256 for every file, so a run can be repeated exactly with `--mode pinned`. `raw/` and
`staging/` are git-ignored.

Because the sources keep changing, a `latest` run gives different numbers over time. Use `pinned`
mode when you need a repeatable result, and keep the manifest with any results you publish.

## Checks

Every source is checked before anything is written, in two layers. Each check produces a quality record
with a status of PASS, WARNING or FAIL; a FAIL stops that source from being written or loaded.

1. **Built-in checks** in each source module: row counts, duplicate keys, coordinates inside NSW or
   Australia, and that all 373 Greater Sydney SA2 codes appear in every ABS table.
2. **Pandera schemas** in [`schemas.py`](schemas.py), one per table: which columns exist, their types,
   which may be empty, allowed values (for example `asset_type` must be `Vehicle`, `Pedestrian` or
   `Re-active Maintenance`) and plausible ranges (counts of 0 or more, median income between $5k and
   $400k). Schemas are strict where the parser decides the columns and loose where the publisher's extra
   columns are kept (traffic lights).

The design follows the validation module of the
[CPI forecast project](https://github.com/JuanVu1810/Australian-CPI-Forecast) (`QualityRecord`, a CSV
quality report, pandera run lazily with coercion, and a fallback warning if pandera isn't installed).
Here pandera 0.32.1 is pinned to the same version that project uses.

Where the records go:

- `staging/data_quality_report.csv`: this run's records.
- `v2.data_quality_results`: a running log, one set of rows appended per run (with `run_at` and `mode`).
- `raw/manifest.json` also records the Python and package versions of the last download run.

Two more guards sit in the parsers. The business parser reads its count columns by position, so it first
checks the turnover band headings and refuses a layout that changed (the June 2021 cube used different
bands). The income and population parsers find their columns by heading.

`verify` re-runs both layers on the staged files. `verify --parity` downloads the older ABS releases
that the v1 files came from (June 2022 businesses, 2020-21 income, and the 2021 population release)
and checks the current parsers reproduce the v1 files exactly, value for value.

The schemas and quality records have their own tests, which use small made-up tables and no network:

```bash
docker compose run --rm --no-deps --entrypoint python etl -m pytest tests -q
```

## Limitations

- **Vintages differ.** Income is the oldest input (2022-23 at the time of writing), and the newest
  ABS releases are months behind the live sources. The score is a blend of dates, not a snapshot.
- **The GTFS bundle is bigger than its name suggests.** The "Greater Sydney" complete GTFS zip (293 MB,
  the same file from the API and the public link) holds 171,090 stops spread across NSW and some
  interstate, so the score should assign stops to SA2s and ignore the rest. About half are stations
  (`location_type` 1) that sit alongside their platforms.
- **A few TfNSW rows have typos.** Three stops and ten traffic lights have coordinates like a latitude
  of 30 instead of -30, a longitude of 1501 instead of 151, or 0,0. They keep an empty geometry, their
  ids are in the manifest, and a source fails its checks if more than 1% are bad. Nothing is corrected
  by guesswork.
- **Licences.** ABS, Data.NSW and TfNSW data is CC BY. OpenStreetMap is ODbL, which has share-alike
  terms for a derived database. The AEC and NSW Spatial Services licences weren't confirmed, so the
  manifest says "not verified".
- **OSM nodes only.** Toilets or crossings mapped as areas or lines aren't counted, as in v1.
- **Zebra crossing counts aren't comparable with v1.** v1 counted nodes tagged `crossing=zebra`
  (1,825 in May 2024). Mappers have since moved to `crossing=uncontrolled` plus `crossing:markings=zebra`,
  so only about 700 nodes still carry the old tag, while about 8,000 carry the new one. `is_zebra`
  covers both, so a score built on it will see many more zebra crossings than v1 did, partly because of
  tagging, not only new crossings.

## Adding a source

Write a module in `etl/sources/` with a `fetch(ctx)` that returns a `Snapshot`, a `parse(snapshot)` that
returns `{table: DataFrame}`, and a `check(outputs, ctx)` that returns a list of `error(...)` or
`warn(...)`. Register it in a `Source(...)` and add the module to `etl/sources/__init__.py`.
