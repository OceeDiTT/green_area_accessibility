"""Geometry helpers, format sniffing and an API-response cache. Requires the 'pipeline' extra."""
import json
import logging
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

log = logging.getLogger(__name__)


def empty_poly():
    return shapely.Polygon()


def unary(geoms):
    return geoms.union_all() if hasattr(geoms, "union_all") else geoms.unary_union


def valid(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = g.copy()
    g["geometry"] = gpd.GeoSeries(shapely.make_valid(np.asarray(g.geometry.values)), index=g.index, crs=g.crs)
    return g


def polygonal(geom):
    """Keep only the polygonal parts of any geometry (intersections can return collections / lines)."""
    if geom is None or geom.is_empty:
        return empty_poly()
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    if geom.geom_type == "GeometryCollection":
        parts = [polygonal(p) for p in geom.geoms]
        parts = [p for p in parts if not p.is_empty]
        return shapely.union_all(parts) if parts else empty_poly()
    return empty_poly()


def read_geo_bytes(raw: bytes, workdir: Path, default_crs: str, fallback_projected_crs: str) -> gpd.GeoDataFrame:
    """Parse GeoPackage / zipped shapefile / GeoJSON from raw bytes (portal download URLs have no extension)."""
    workdir.mkdir(parents=True, exist_ok=True)
    if raw[:15] == b"SQLite format 3":                                     # GeoPackage
        path = workdir / "_download.gpkg"
        path.write_bytes(raw)
        frames = []
        try:
            import pyogrio
            for name, gtype in pyogrio.list_layers(str(path)):
                if gtype and "polygon" in str(gtype).lower():
                    frames.append(gpd.read_file(path, layer=name))
        except Exception as e:                                              # older pyogrio / odd file
            log.warning("layer listing failed (%s); reading default layer", e)
        if not frames:
            frames = [gpd.read_file(path)]
        crs = frames[0].crs
        frames = [f.to_crs(crs) if f.crs is not None and crs is not None else f for f in frames]
        g = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=crs)
    elif raw[:2] == b"PK":                                                  # zipped shapefile
        path = workdir / "_download.zip"
        path.write_bytes(raw)
        g = gpd.read_file(f"zip://{path.resolve().as_posix()}")
    elif raw.lstrip()[:1] in (b"{", b"["):                                  # GeoJSON
        obj = json.loads(raw.decode("utf-8-sig"))
        feats = obj["features"] if isinstance(obj, dict) else obj
        g = gpd.GeoDataFrame.from_features(feats)
    else:
        raise ValueError(f"Unrecognised geo format; content starts with {raw[:60]!r}")
    if g.crs is None:                                                       # guess from coordinate magnitude
        minx, miny, maxx, maxy = g.total_bounds
        g = g.set_crs(default_crs if max(abs(minx), abs(maxx)) <= 180 else fallback_projected_crs)
    return g


class Cache:
    """Disk cache for raw API results (GeoPackage). Entries older than max_age_days are rebuilt."""

    def __init__(self, root: Path, refresh: bool = False, max_age_days: float = 30):
        self.root, self.refresh, self.max_age = Path(root), refresh, max_age_days * 86400
        self.root.mkdir(parents=True, exist_ok=True)

    def _fresh(self, p: Path) -> bool:
        return p.exists() and not self.refresh and (time.time() - p.stat().st_mtime) < self.max_age

    def gdf(self, name: str, builder) -> gpd.GeoDataFrame:
        p = self.root / f"{name}.gpkg"
        if self._fresh(p):
            log.info("cache hit: %s", name)
            return gpd.read_file(p)
        g = builder()
        if len(g):
            g.to_file(p, driver="GPKG")
        log.info("fetched %s: %s features", name, f"{len(g):,}")
        return g
