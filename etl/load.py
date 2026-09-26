"""Load the cleaned tables into PostGIS, in a schema of their own (vibrancy), so any other tables in the database stay untouched."""
from __future__ import annotations

import json
import os

import geopandas as gpd
import pandas as pd
from geoalchemy2 import Geometry
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from .core import ROOT, utc_now

SCHEMA = "vibrancy"

# Keys and indexes added after each table is written (name -> SQL statements, {t} is the table).
_INDEXES = {
    "sa2_boundaries": ['ALTER TABLE {t} ADD PRIMARY KEY ("SA2_CODE21")'],
    "income": ['ALTER TABLE {t} ADD PRIMARY KEY ("SA2_CODE21")', 'CREATE INDEX ON {t} (median_income)'],
    "population": ['ALTER TABLE {t} ADD PRIMARY KEY ("SA2_CODE21")'],
    "businesses": ['CREATE INDEX ON {t} ("SA2_CODE21")', 'CREATE INDEX ON {t} (industry_code)'],
    "stops": ['CREATE INDEX ON {t} (stop_id)'],
    "polling_places": ['CREATE INDEX ON {t} (polling_place_id)'],
    "schools": ['CREATE INDEX ON {t} ("USE_ID")'],
}


def connection_settings(credentials_file: str | None = None, host: str | None = None,
                        database: str | None = None) -> dict:
    """Where to load. By default the same rules as the notebook: DB_* environment variables (what docker compose
    sets, for its own database), then Credentials.json. `credentials_file` says to use that file instead of the
    environment, and `host` and `database` override what it names (for example host.docker.internal to reach
    a PostgreSQL that runs on your own computer, from inside Docker)."""
    if credentials_file:
        with open(ROOT / credentials_file, encoding="utf-8") as f:
            c = json.load(f)
        c.setdefault("database", c["user"])
    elif os.environ.get("DB_PASSWORD"):
        c = {"host": os.environ.get("DB_HOST", "localhost"), "port": int(os.environ.get("DB_PORT", "5432")),
             "user": os.environ.get("DB_USER", "postgres"), "password": os.environ["DB_PASSWORD"],
             "database": os.environ.get("DB_NAME", os.environ.get("DB_USER", "postgres"))}
    else:
        path = os.environ.get("CREDENTIALS_FILE", str(ROOT / "Credentials.json"))
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        c.setdefault("database", c["user"])
    if host:
        c["host"] = host
    if database:
        c["database"] = database
    return c


def describe(settings: dict) -> str:
    """The target as host:port/database, never the password."""
    return f"{settings['host']}:{settings['port']}/{settings['database']}"


def engine(settings: dict | None = None):
    c = settings or connection_settings()
    url = URL.create("postgresql+psycopg2", username=c["user"], password=c["password"],
                     host=c["host"], port=c["port"], database=c["database"])
    return create_engine(url)


def _comment(source, release: str, retrieved: str) -> str:
    return f"{source.title}. Release: {release}. Retrieved {retrieved[:10]}. Licence: {source.licence}."


def load(tables: dict, table_sources: dict, records: dict, sources_by_id: dict, quality=None, settings: dict | None = None,
         log=print) -> list:
    """Write `tables` (name -> DataFrame) to schema vibrancy, and every manifest record to vibrancy.etl_manifest.

    `table_sources` maps a table name to its Source, `records` is the whole manifest (source id ->
    record) and `sources_by_id` maps source ids to Sources. Returns (table, problem) pairs for tables
    that failed to load.
    """
    eng, failures = engine(settings), []
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    for name, df in tables.items():
        try:
            if isinstance(df, gpd.GeoDataFrame):
                # A table with some empty geometries (polling places) would otherwise become a generic GEOMETRY.
                kinds = df.geometry.dropna().geom_type.unique()
                gtype = kinds[0].upper() if len(kinds) == 1 else "GEOMETRY"
                df.to_postgis(name, eng, schema=SCHEMA, if_exists="replace", index=False,
                              dtype={"geom": Geometry(gtype, srid=4326)})
                with eng.begin() as conn:  # geopandas may still create a generic GEOMETRY column
                    have = conn.execute(text("SELECT type FROM geometry_columns WHERE f_table_schema=:s "
                                             "AND f_table_name=:t"), {"s": SCHEMA, "t": name}).scalar()
                    if gtype != "GEOMETRY" and have != gtype:
                        conn.execute(text(f'ALTER TABLE {SCHEMA}."{name}" ALTER COLUMN geom '
                                          f'TYPE geometry({gtype}, 4326)'))
            else:
                df.to_sql(name, eng, schema=SCHEMA, if_exists="replace", index=False)
            src = table_sources[name]
            rec = records[src.id]
            with eng.begin() as conn:
                t = f'{SCHEMA}."{name}"'
                for stmt in _INDEXES.get(name, []):
                    conn.execute(text(stmt.format(t=t)))
                if isinstance(df, gpd.GeoDataFrame):
                    have = conn.execute(text(
                        "SELECT count(*) FROM pg_indexes WHERE schemaname=:s AND tablename=:t "
                        "AND indexdef ILIKE '%gist%'"), {"s": SCHEMA, "t": name}).scalar()
                    if not have:
                        conn.execute(text(f'CREATE INDEX ON {t} USING GIST (geom)'))
                comment = _comment(src, rec["release"], rec["retrieved_at"]).replace("'", "''")
                conn.execute(text(f"COMMENT ON TABLE {t} IS '{comment}'"))
            with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(f'ANALYZE {SCHEMA}."{name}"'))  # so the planner has statistics
            log(f"  loaded {SCHEMA}.{name}: {len(df):,} rows")
        except Exception as e:  # keep loading the other tables
            failures.append((name, str(e).splitlines()[0]))
            log(f"  FAILED {SCHEMA}.{name}: {str(e).splitlines()[0]}")

    rows = []
    for sid, rec in records.items():
        src = sources_by_id.get(sid)
        if src is None:
            continue
        rows.append({"source_id": sid, "title": src.title, "release": rec["release"], "url": rec["url"],
                     "retrieved_at": rec["retrieved_at"], "licence": src.licence, "attribution": src.attribution,
                     "files": json.dumps(rec["files"], sort_keys=True),
                     "extra": json.dumps(rec.get("extra", {}), sort_keys=True), "loaded_at": utc_now()})
    if quality is not None and len(quality):  # a running log: each run appends its records
        quality.to_sql("data_quality_results", eng, schema=SCHEMA, if_exists="append", index=False)
        log(f"  added {len(quality)} rows to {SCHEMA}.data_quality_results")
    if rows:
        pd.DataFrame(rows).to_sql("etl_manifest", eng, schema=SCHEMA, if_exists="replace", index=False)
        log(f"  loaded {SCHEMA}.etl_manifest: {len(rows)} sources")
    return failures
