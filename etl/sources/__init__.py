"""The source registry. Order matters: the SA2 boundaries come first because other checks use them."""
from . import abs as abs_sources
from . import aec, nsw, osm, tfnsw

SOURCES = (abs_sources.SOURCES + nsw.SOURCES + aec.SOURCES + tfnsw.SOURCES + osm.SOURCES)
BY_ID = {s.id: s for s in SOURCES}
TABLES = {t: s for s in SOURCES for t in s.outputs}
