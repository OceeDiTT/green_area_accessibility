"""Hybrid green-space layer: OSM polygons + the city's official polygons, minus the exclusion zone (Collserola)."""
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import shapely

from .geo import empty_poly, polygonal, unary


@dataclass
class GreenResult:
    union: object
    patches: gpd.GeoDataFrame
    report: dict


def _union(gdf, clip):
    if gdf is None or len(gdf) == 0:
        return empty_poly()
    return polygonal(shapely.make_valid(unary(gdf.geometry)).intersection(clip))


def _km2(geom) -> float:
    return float(geom.area) / 1e6


def build_green(osm, official: dict, exclusion, city_poly, min_green_m2: float, crs: str) -> GreenResult:
    """Dissolve everything (no double counting), remove the exclusion zone, keep contiguous patches >= min size."""
    osm_u = _union(osm, city_poly)
    off_by = {label: _union(g, city_poly) for label, g in official.items()}
    off_u = shapely.union_all(list(off_by.values())) if off_by else empty_poly()
    combined = polygonal(shapely.union_all([osm_u, off_u]))

    excl = empty_poly()
    if exclusion is not None and len(exclusion):
        excl = polygonal(shapely.make_valid(unary(exclusion.geometry)))
    final = polygonal(combined.difference(excl)) if not excl.is_empty else combined

    parts = [p for p in shapely.get_parts(final) if not p.is_empty and p.area >= min_green_m2]
    patches = gpd.GeoDataFrame(geometry=parts, crs=crs).reset_index(drop=True)
    patches["area_m2"] = patches.geometry.area
    union = shapely.union_all(list(patches.geometry)) if len(patches) else empty_poly()
    shapely.prepare(union)

    report = {
        "osm_km2": _km2(osm_u),
        "official_km2": _km2(off_u),
        "official_by_layer_km2": {k: _km2(v) for k, v in off_by.items()},
        "combined_before_exclusion_km2": _km2(combined),
        "excluded_km2": _km2(combined) - _km2(final),
        "final_km2": _km2(union),
        "patches": int(len(patches)),
        "exclusion_zone_found": bool(not excl.is_empty),
    }
    if not osm_u.is_empty and not off_u.is_empty:
        report["osm_only_km2"] = _km2(osm_u.difference(off_u))
        report["official_only_km2"] = _km2(off_u.difference(osm_u))
        report["official_share_also_in_osm"] = float(osm_u.intersection(off_u).area / off_u.area) if off_u.area else 0.0
    return GreenResult(union=union, patches=patches, report=report)


def register_match_rate(points, union, tolerance_m: float):
    """Share of the city's registered parks that lie within `tolerance_m` of the hybrid green layer."""
    if points is None or len(points) == 0 or union.is_empty:
        return None
    buf = union.buffer(tolerance_m)
    shapely.prepare(buf)
    return float(shapely.intersects(np.asarray(points.geometry.values), buf).mean())
