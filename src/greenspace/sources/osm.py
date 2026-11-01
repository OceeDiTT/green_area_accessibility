"""OpenStreetMap layers via the Overpass API (through osmnx)."""
import logging

import geopandas as gpd

from ..geo import unary, valid
from ..tabular import norm

log = logging.getLogger(__name__)


def query_polygon(units_proj: gpd.GeoDataFrame, crs_wgs84: str, margin_deg=0.0005):
    """Area of interest = the city's own unit boundaries (slightly buffered and simplified for Overpass)."""
    poly = unary(units_proj.to_crs(crs_wgs84).geometry).buffer(margin_deg)
    return poly.simplify(0.0001, preserve_topology=True)


def _ox():
    import osmnx as ox
    ox.settings.use_cache = True
    ox.settings.timeout = 300
    return ox


def fetch_green(poly_wgs, tags: dict, crs_proj: str) -> gpd.GeoDataFrame:
    g = _ox().features_from_polygon(poly_wgs, tags)
    g = g[g.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    for col, bad in (("access", ["private", "no", "customers"]), ("garden:type", ["residential"])):
        if col in g.columns:
            g = g[~g[col].isin(bad)]
    keep = [c for c in ("leisure", "landuse", "name") if c in g.columns]
    g = g[keep + ["geometry"]].reset_index(drop=True)
    for c in keep:
        g[c] = g[c].astype(str)
    return valid(g).to_crs(crs_proj)


def fetch_stations(poly_wgs, crs_proj: str) -> gpd.GeoDataFrame:
    g = _ox().features_from_polygon(poly_wgs, {"railway": ["station"]})
    g = g[g.geom_type.isin(["Point", "Polygon", "MultiPolygon"])].copy().to_crs(crs_proj)
    g["geometry"] = g.geometry.centroid
    g["name"] = g["name"].astype(str) if "name" in g.columns else ""
    return g[["name", "geometry"]].reset_index(drop=True)


def fetch_buildings(poly_wgs, min_area_m2: float, crs_proj: str) -> gpd.GeoDataFrame:
    """Building centroids weighted by footprint area (proxy for where people live)."""
    g = _ox().features_from_polygon(poly_wgs, {"building": True})
    g = g[g.geom_type.isin(["Polygon", "MultiPolygon"])].copy().to_crs(crs_proj)
    g["w"] = g.geometry.area
    g = g[g["w"] >= min_area_m2]
    return gpd.GeoDataFrame({"w": g["w"].values}, geometry=g.geometry.centroid.values, crs=crs_proj).reset_index(drop=True)


def fetch_exclusion_zone(poly_wgs, patterns: list, tags: dict, crs_proj: str) -> gpd.GeoDataFrame:
    """Polygons (e.g. the Collserola natural park) whose name matches one of `patterns`. Empty on failure."""
    empty = gpd.GeoDataFrame({"name": []}, geometry=[], crs=crs_proj)
    try:
        g = _ox().features_from_polygon(poly_wgs, tags)
    except Exception as e:
        log.warning("exclusion-zone query failed: %s", e)
        return empty
    g = g[g.geom_type.isin(["Polygon", "MultiPolygon"])]
    if g.empty or "name" not in g.columns:
        return empty
    pats = [norm(p) for p in patterns]
    g = g[g["name"].fillna("").map(lambda n: any(p in norm(n) for p in pats))]
    if g.empty:
        return empty
    g = g[["name", "geometry"]].reset_index(drop=True)
    g["name"] = g["name"].astype(str)
    return valid(g).to_crs(crs_proj)
