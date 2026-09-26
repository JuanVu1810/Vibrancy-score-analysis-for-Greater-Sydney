# Vibrancy index for Greater Sydney

Which Greater Sydney SA2s have the conditions associated with lively, varied, walkable areas, and how much can that
ranking be trusted? This project builds a vibrancy index for the 373 Greater Sydney SA2s (ASGS Edition 3, 2021) from
public data, and tells the result as a data story.

The index is a proxy. It measures the conditions that allow street activity, from open data on businesses, residents,
transport, streets and land use. It does not measure how many people are actually there.

**Status.** The data pipeline is built and tested: it downloads 15 sources, then cleans, checks and loads them into
PostGIS as 17 tables. The indicators and the index are not built yet, so `vibrancy/` holds a placeholder story page and an empty
skeleton of the methodology book. This README will link to both when they have content.

## The data

| Publisher | What | Licence |
|---|---|---|
| Australian Bureau of Statistics | SA2 boundaries, counts of businesses by industry, personal income, regional population, Census mesh block counts | CC BY 4.0 |
| Transport for NSW | Timetable stops (GTFS), traffic light locations | CC BY |
| NSW Department of Education | School intake zones (catchments) | CC BY |
| NSW Spatial Services | Health facilities (hospitals) | not verified |
| Australian Electoral Commission | Polling places, 2025 federal election | not verified |
| OpenStreetMap contributors | Public toilets and drinking water, pedestrian crossings, the walkable road network, everyday shops | ODbL |
| City of Sydney | Trees, stairs and mobility parking (inner city only), and pedestrian count sites (inner city only, kept for checking the index) | CC BY 4.0 |

Every file is recorded in `raw/manifest.json` with its URL, retrieval time, size and SHA-256, and the ETL refuses a file
that does not match. A fresh download gives newer numbers over time, so keep the manifest with any results you publish.
The details of each table, and the known limits of each source, are in [etl/README.md](etl/README.md).

## Run it yourself

You need [Docker](https://docs.docker.com/get-docker/) with Compose, about 5 GB of free disk space (the two Docker images are
2.2 GB and `raw/` is 2.1 GB), and a connection that can download about 750 MB. It was developed on Docker Desktop for Windows with the WSL 2 backend; run the commands
below from a WSL, Linux or macOS terminal.

```bash
cp .env.example .env          # first time only. This overwrites an existing .env, so skip it if you have one
# edit .env (not .env.example) and set DB_PASSWORD to a private password
docker compose build etl      # first time, and whenever requirements.lock changes
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" --entrypoint python etl download_data.py   # step 1
docker compose run --rm etl   # step 2: unzip, clean, check, and load into schema "vibrancy"
```

Step 1 saves every source under `raw/` (it skips what is already there and carries on after a cut-off connection).
Step 2 reads only `raw/`, checks each file against its checksum, and writes the cleaned tables to `staging/` and to the
`vibrancy` schema of the PostGIS database that Docker Compose starts. Both folders are git-ignored. Unzipping the downloads is
what takes `raw/` to about 2 GB.

- **Optional key.** A free Transport for NSW API key (register at <https://opendata.transport.nsw.gov.au>) makes the
  timetable download more reliable. Put `TFNSW_API_KEY=...` in your private `.env`, never in `.env.example`.
- **The database** is published on `127.0.0.1:5433`, so it cannot be reached from other machines. User, database and
  port can be changed in `.env`.
- **Where the checks are.** `staging/data_quality_report.csv` lists the result of every check as PASS, WARNING or FAIL.
- **Tests.** `docker compose run --rm --no-deps --entrypoint python etl -m pytest tests -q`
- **More options.** Running one source, loading into a PostgreSQL server you already have, starting again from scratch,
  and viewing the tables in pgAdmin are in [etl/README.md](etl/README.md).
- **As a notebook.** [etl_walkthrough.ipynb](etl_walkthrough.ipynb) runs the same pipeline one explained stage at a time.

### Build the methodology book

The book in [vibrancy/book/](vibrancy/book/) is a [Jupyter Book](https://jupyterbook.org) 2 site (Python 3.9 or newer).
The first build asks to download Node.js, which Jupyter Book needs, and installs it beside the package.

```bash
cd vibrancy/book
pip install -r requirements.txt
jupyter-book build --html      # the site is written to vibrancy/book/_build/html
```

## Files

| Path | Purpose |
|---|---|
| `download_data.py` | Downloads every source into `raw/` and records it in `raw/manifest.json` |
| `etl/` | Unzips, cleans, checks and loads the downloads (`python -m etl run`); its README describes every table |
| `etl_walkthrough.ipynb` | The pipeline as an explained notebook |
| `vibrancy/` | The story page (a placeholder for now), and in `vibrancy/book/` the methodology book |
| `tests/` | Tests for the downloader, the unzipping, the parsers and the quality checks |
| `docker-compose.yml`, `Dockerfile` | The PostGIS database and the Python environment |
| `requirements.txt`, `requirements.lock` | The direct dependencies, and a full pin of every package (the Docker image installs the lock file) |
| `.env.example` | Template for the private `.env` |

## Credits and licences

- OpenStreetMap data is © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under the
  Open Database Licence (ODbL), which has share-alike terms for a derived database.
- The boundaries and statistics are © the Australian Bureau of Statistics. Transport for NSW, NSW Government and City
  of Sydney data are used under their open data licences, as in the table above.
- The AEC and NSW Spatial Services licences were not confirmed. Check each licence before you reuse or redistribute
  the data.
