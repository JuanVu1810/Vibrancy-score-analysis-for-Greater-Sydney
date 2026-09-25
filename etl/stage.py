"""Read and write the cleaned tables in staging/: GeoPackage for spatial tables, CSV for the rest."""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from .core import STAGING


def write_staged(name: str, df) -> str:
    STAGING.mkdir(parents=True, exist_ok=True)
    if isinstance(df, gpd.GeoDataFrame):
        path = STAGING / f"{name}.gpkg"
        path.unlink(missing_ok=True)
        (STAGING / f"{name}.csv").unlink(missing_ok=True)
        df.to_file(path, layer=name, driver="GPKG")
    else:
        path = STAGING / f"{name}.csv"
        (STAGING / f"{name}.gpkg").unlink(missing_ok=True)
        df.to_csv(path, index=False, encoding="utf-8")
    return path.name


def read_staged(name: str):
    """A previously staged table, or None."""
    gpkg, csv = STAGING / f"{name}.gpkg", STAGING / f"{name}.csv"
    if gpkg.exists():
        return gpd.read_file(gpkg, layer=name).rename_geometry("geom")
    if csv.exists():
        return pd.read_csv(csv)
    return None


def get_table(ctx, name: str):
    """A table from this run if it was built, otherwise from staging/, otherwise None."""
    if name in ctx.frames:
        return ctx.frames[name]
    return read_staged(name)


def greater_sydney_codes(ctx):
    """The 373 Greater Sydney SA2 codes from the boundary table, or None if it isn't available."""
    sa2 = get_table(ctx, "sa2_boundaries")
    return None if sa2 is None else set(int(c) for c in sa2["SA2_CODE21"])
