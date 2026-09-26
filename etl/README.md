# ETL for the Greater Sydney vibrancy index

This cleans the downloaded source datasets into a consistent shape, checks them, and loads them into PostGIS. It does
not download anything: [`download_data.py`](../download_data.py) does that first. Every source has a documented
publisher, a licence, and a record of exactly which file was used.

It never touches `data/`, the notebooks, or the tables in the `public` schema. Cleaned tables go to
`staging/` (files) and to a new `v2` schema in the database.

## Two steps

1. **Download.** `python download_data.py` saves every source under `raw/` and records it in `raw/manifest.json`
   (URL, date, size and SHA-256 of each file). Its docstring says how to run it, and which links to change for a newer
   release. It also downloads the three City of Sydney datasets (trees, stairs, mobility parking).
2. **Clean, check, load.** `python -m etl run` (below) reads only the files in `raw/`. For each source it checks the
   file against its checksum in the manifest, unzips it if it is a zip, parses it, runs the checks, writes `staging/`
   and loads schema `v2`. It uses no network. A source that isn't in the manifest yet is reported as `NOT RUN` with
   the command that downloads it, and the others carry on.

## Quick start

```bash
cp .env.example .env          # first time only; skip if you already have one
# put your private DB_PASSWORD in .env (a TfNSW key is optional, see below)
docker compose build etl      # first time, and whenever requirements.lock changes
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" --entrypoint python etl download_data.py   # step 1
docker compose run --rm etl   # step 2: clean, check, and load into schema v2
```

The other commands:

```bash
docker compose run --rm etl list                       # sources and the tables they make
docker compose run --rm etl run --only abs_business    # just one source
docker compose run --rm --no-deps etl run --no-db      # files in staging/ only, no database
```

### Which database it loads into

pgAdmin is optional. It is a graphical tool for viewing and managing PostgreSQL; it is not the database
server itself. The normal Docker setup includes its own PostgreSQL/PostGIS server, so users do not need to
install either pgAdmin or PostgreSQL on their computer.

`docker compose run --rm etl` loads into the database docker compose starts (port 5433, separate from any
PostgreSQL you have installed). If you have pgAdmin and want to use it to inspect this Docker database, register
a server in pgAdmin with these connection settings (start it first with `docker compose up -d db` if it is not
already running):

```text
Host name/address: localhost
Port:              5433 (or the DB_PORT value in .env)
Maintenance DB:    postgres (or the DB_NAME value in .env)
Username:          postgres (or the DB_USER value in .env)
Password:          the DB_PASSWORD value in .env
```

After the ETL finishes, its tables appear under **Databases > postgres > Schemas > v2** in pgAdmin. Changing
`DB_NAME` changes the database name shown in that path.

Alternatively, to load into a separate PostgreSQL server that already runs on your computer, such as one your
pgAdmin shows on port 5432 and the notebook's `Credentials.json` describes, use:

```bash
docker compose run --rm --no-deps etl run \
    --credentials Credentials.json --db-host host.docker.internal --db-name postgres
```

`--credentials` takes the user, password and port from that file. `--db-host host.docker.internal` is needed
because "localhost" inside Docker means the container itself. `--db-name postgres` is needed because
`Credentials.json` names a database called `localhost`, which doesn't exist on that server (its only database is
`postgres`). Either way the ETL only creates and replaces tables in a schema called `v2`; your `public` tables and
any other schemas are left alone.

Run it in Docker: the pinned geospatial libraries aren't installed on a plain host Python. Without
Docker, `python -m etl ...` works in an environment built from `requirements.lock`.

## From scratch, and starting over

Everything from a clean project folder to the loaded database. You need Docker Desktop running and this branch
checked out (`git switch v2-etl`).

```bash
# 1. First time only: your private settings. Put a DB_PASSWORD in .env; a TFNSW_API_KEY is optional (see below).
cp .env.example .env

# 2. Build the image (first time, and whenever requirements.lock changes; later builds are cached).
docker compose build etl

# 3. Download everything into raw/ (it skips what is already there, and carries on after a cut-off).
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" --entrypoint python etl download_data.py

# 4. Unzip, clean, check, and load everything into the Docker database (port 5433).
docker compose run --rm etl

# 4b. Or load into the PostgreSQL that pgAdmin shows on port 5432 (schema v2 only; your public tables are untouched).
docker compose run --rm --no-deps etl run --credentials Credentials.json --db-host host.docker.internal --db-name postgres
```

Step 3 downloads about 750 MB (the transit feed is 290 MB and the OpenStreetMap extract 260 MB). Step 4 unzips it to
about 2.4 GB and reads it. ABS cuts big downloads off now and then; the downloader resumes them, so if you see
"interrupted ... resuming" that is normal. The download is the slow part on a slow connection, so expect anything from
a few minutes to most of an hour. Step 4 can be repeated, for a second database for example, without downloading again.

Where to look afterwards: `raw/` (the downloads and their unzipped folders, plus `raw/manifest.json`), `staging/`
(the cleaned files and `data_quality_report.csv`, which is where the results of the checks are), and schema `v2` in the database.

**To wipe everything the ETL made and start again** (your `data/` folder, the notebooks and your `public` tables are never touched):

```bash
rm -rf raw staging                                    # the downloads and the cleaned files
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA IF EXISTS v2 CASCADE"'   # Docker database
```

For the pgAdmin database on 5432, run `DROP SCHEMA IF EXISTS v2 CASCADE;` in pgAdmin's Query Tool on the `postgres`
database. If `rm` says permission denied (files written by Docker as root), run
`docker run --rm -v "$PWD":/work -w /work data2001assignments-etl:latest rm -rf /work/raw /work/staging` instead.

## The notebook: `etl_walkthrough.ipynb`

The same pipeline as a notebook: each stage is explained, run and its result
shown (the sources, one source step by step, the code that does the work, the full run, what was produced, a map, the
checks, and the tables in the database). It also has a section mapping every Docker command to the code it runs.

Settings are in its first code cell: which `SOURCES` to run (all by default) and `LOAD_TO` (`None` for files only, or
`"pgadmin"` to load your port 5432 database). It loads nothing into a database unless you set `LOAD_TO`. It needs the
files in `raw/` from `download_data.py` first.

**In Docker, nothing to install** (runs every cell and saves the result with its outputs in `output/`):

```bash
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" -e HOME=/tmp --entrypoint jupyter etl \
    nbconvert --to notebook --execute etl_walkthrough.ipynb --output-dir output \
    --output etl_walkthrough.executed.ipynb --ExecutePreprocessor.kernel_name=python3 --ExecutePreprocessor.timeout=-1
```

**In VS Code**, use a Python 3.11 environment that has the ETL's libraries. Set one up once with conda (the
`-c requirements.lock` makes pip use the same versions as the Docker image):

```bash
conda create -n bustling -c conda-forge --override-channels python=3.11 -y
conda activate bustling
pip install -r etl/requirements.txt -c requirements.lock
```

Then open the notebook and choose the `bustling` environment as its kernel. To try it small first, download just those two
sources (`python download_data.py abs_population hospitals`) and set `SOURCES = ["abs_population", "hospitals"]`.

## Transport for NSW (stops and traffic lights)

The TfNSW Open Data Hub refused scripted downloads for hours on 25 Sep 2026 (a CDN block that answered 403 to
everything, even its home page) and then stopped. `download_data.py` therefore has two routes for the GTFS feed: the
API when `TFNSW_API_KEY` is set, and otherwise the public download link. If the site blocks you, save the file from the
portal's page by hand as `raw/<source>/<date>/<filename>` (the name is in the downloader's table) and run the
downloader again: it picks the file up and records it in the manifest.

The API key is free: register at <https://opendata.transport.nsw.gov.au>, create an application, and add
`TFNSW_API_KEY=...` to your private **`.env`**. It's sent as `Authorization: apikey <key>` and is never
written to the manifest. **Don't put it in `.env.example`**: that file is tracked by git and would be committed.

## What it produces

| Table (schema v2) | Source | Publisher | Notes |
|---|---|---|---|
| `sa2_boundaries` | ASGS Edition 3 SA2 (2021) | ABS | Greater Sydney only (373 SA2s) |
| `businesses` | Counts of Australian Businesses, data cube 9 | ABS | NSW, industries A to S; industry X (unknown) dropped |
| `income` | Personal Income in Australia, Table 1 (total income) | ABS | NSW SA2s, newest year in the workbook |
| `population` | Regional population by age and sex | ABS | Greater Sydney SA2s, persons, five-year bands |
| `stops` | Timetables Complete GTFS, `stops.txt` | TfNSW | Blank `location_type` becomes 0 (a stop); 1 is a station. A few rows with typo coordinates keep an empty geometry |
| `polling_places` | 2025 federal election polling places | AEC | NSW; places without coordinates kept with an empty geometry |
| `schools` | School intake zones (catchments) | NSW Dept of Education | Future catchments replace current ones |
| `traffic_lights` | Traffic Lights Location | TfNSW | `asset_type` is `Vehicle` or `Pedestrian` (older files' VEH/PED are mapped to these); rows with typo coordinates keep an empty geometry |
| `hospitals` | NSW Features of Interest, Health Facilities | NSW Spatial Services | Includes private hospitals and a few ACT ones |
| `public_amenities`, `crossings` | OpenStreetMap, Geofabrik NSW extract | OpenStreetMap contributors (ODbL) | Mapped points only; `crossings.is_zebra` covers the old and new zebra tagging (see Limitations) |
| `mesh_blocks` | Census 2021 mesh block counts, plus the ABS allocation file | ABS | Greater Sydney only (60,881 blocks): dwellings and persons, with each block's SA1 and SA2 |
| `roads` | OpenStreetMap, the same Geofabrik extract | OpenStreetMap contributors (ODbL) | The walkable road network, for AUO-style walkability (about 150,000 lines) |
| `daily_living_shops` | OpenStreetMap, the same extract | OpenStreetMap contributors (ODbL) | Supermarkets and convenience stores (including newsagents and petrol stations), as AUO defines them; shops mapped as buildings are included at their centre |
| `cos_trees`, `cos_stairs`, `cos_mobility_parking` | City of Sydney open data (ArcGIS layers) | City of Sydney (CC BY 4.0) | Inner city only (about 5 x 8 km), so they are extras, not Greater Sydney layers. The publisher's columns are kept, lower-cased (49,640 trees, 523 stairs and 365 mobility parking spaces in Sep 2026) |

Key columns keep the publishers' names (`SA2_CODE21`, `USE_ID`, and so on); new tables use lower-case `snake_case`
columns.
`v2.etl_manifest` lists, for every source, the release, URL, retrieval time and licence, and each
table carries a `COMMENT` with the same.

## Where the files are kept

Downloads land in `raw/<source>/<date>/`. `raw/manifest.json` records URL, retrieval time, size and SHA-256 for every
file, and the ETL refuses to read a file that does not match its checksum, so a result can be traced to the exact
bytes it came from. `raw/` and `staging/` are git-ignored. To get a newer release, change the link in
`download_data.py` and download again.

**Zip files are unzipped first.** Every zip a source delivers (the SA2 boundaries, the school
catchments, the GTFS feed) is unzipped into a folder beside it before anything is read, so
`raw/asgs_sa2/2026-09-25/SA2_2021_AUST_SHP_GDA2020.zip` also gives you
`raw/asgs_sa2/2026-09-25/SA2_2021_AUST_SHP_GDA2020/` with the shapefile inside. The zip is kept, so its checksum can
still be checked, and a zip inside a zip is unzipped too. An earlier extraction is reused, and a file that would
land outside its folder (a path containing `..`) is refused. Together the three zips unzip to about 1.5 GB, most of
it the GTFS feed's `shapes.txt` (about 1 GB).

Because the sources keep changing, a fresh download gives different numbers over time. Keep the manifest with any
results you publish.

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
- `v2.data_quality_results`: a running log, one set of rows appended per run (with `run_at`).

Two more guards sit in the parsers. The business parser reads its count columns by position, so it first
checks the turnover band headings and refuses a layout that changed (the June 2021 cube used different
bands). The income and population parsers find their columns by heading.

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
- **OSM nodes only.** Toilets or crossings mapped as areas or lines aren't counted.
- **Roads leave out footpaths.** The walkable network uses residential, unclassified, living, tertiary,
  secondary, primary, trunk and pedestrian streets, as AUO's "walkable road network that excluded highways
  and freeways" does. Footways and paths (mostly sidewalks beside a road) and service roads are left out, so
  a few places that are joined only by a footpath or a laneway look less connected than they are.
- **Zebra crossings are tagged two ways.** Older mapping uses `crossing=zebra` (about 700 nodes now); newer mapping
  uses `crossing=uncontrolled` plus `crossing:markings=zebra` (about 8,000). `is_zebra` covers both, so a count of
  zebra crossings reflects tagging habits as well as real crossings.

## Adding a source

Add its link to `download_data.py` (the id there is the source's id here). Then write a module in `etl/sources/` with a
`parse(snapshot)` that returns `{table: DataFrame}` and a `check(outputs, ctx)` that returns a list of `error(...)` or
`warn(...)`. Register it in a `Source(...)` and add the module to `etl/sources/__init__.py`.
