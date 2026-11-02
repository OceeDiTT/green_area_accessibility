"""Explain why a unit has few / no resident sample points (offline: reads the live run + the API cache)."""
from pathlib import Path

import numpy as np
import pandas as pd

from .tabular import norm


def unit_report(units, patches, buildings, osm_green, names, grid_step: float = 50.0) -> pd.DataFrame:
    """For each selected unit: how many buildings exist, how many fall inside the green layer, and which source covers them."""
    import geopandas as gpd
    import shapely
    from .geo import unary

    pats = [norm(n) for n in names]
    sel = units[units["barri"].map(lambda b: any(p in norm(b) for p in pats))]
    green_u = unary(patches.geometry)
    osm_u = unary(osm_green.geometry) if osm_green is not None and len(osm_green) else shapely.Polygon()
    shapely.prepare(green_u)
    shapely.prepare(osm_u)
    rows = []
    for _, u in sel.iterrows():
        poly = u.geometry
        b = buildings[buildings.geometry.within(poly)] if buildings is not None else buildings
        pts_b = np.asarray(b.geometry.values) if b is not None else np.array([])
        in_green = shapely.intersects(pts_b, green_u) if len(pts_b) else np.array([], dtype=bool)
        in_osm = shapely.intersects(pts_b, osm_u) if len(pts_b) else np.array([], dtype=bool)
        minx, miny, maxx, maxy = poly.bounds
        xx, yy = np.meshgrid(np.arange(minx + grid_step / 2, maxx, grid_step), np.arange(miny + grid_step / 2, maxy, grid_step))
        g = gpd.GeoSeries(gpd.points_from_xy(xx.ravel(), yy.ravel()), crs=units.crs)
        g = g[g.within(poly)]
        g_green = shapely.intersects(np.asarray(g.values), green_u) if len(g) else np.array([], dtype=bool)
        rows.append({
            "barri": u["barri"], "area_km2": round(poly.area / 1e6, 3),
            "green_cover_pct": round(float(u["green_cover_pct"]), 1) if "green_cover_pct" in u else None,
            "buildings": int(len(pts_b)), "in_green_layer": int(in_green.sum()), "of_which_in_OSM_green": int(in_osm.sum()),
            "buildings_kept": int((~in_green).sum()),
            "grid_points": int(len(g)), "grid_points_outside_green": int((~g_green).sum()),
        })
    return pd.DataFrame(rows)


def inspect_units(cfg, data_dir, names) -> pd.DataFrame:
    import geopandas as gpd

    from .store import RunStore
    store = RunStore(data_dir, cfg.city.slug, create=False)
    rid = store.latest_id()
    if rid is None:
        raise RuntimeError("No published run to inspect. Run: greenspace run")
    gp = store.path(rid) / "green_metrics.gpkg"
    units, patches = gpd.read_file(gp, layer="units"), gpd.read_file(gp, layer="green_patches")
    cache = Path(data_dir) / "cache" / cfg.city.slug

    def newest(prefix):
        files = sorted(cache.glob(f"{prefix}*.gpkg"), key=lambda p: p.stat().st_mtime)
        return gpd.read_file(files[-1]) if files else None

    buildings = newest("osm_buildings_")
    if buildings is None:
        raise RuntimeError(f"No cached building footprints in {cache} (the run used grid sampling?)")
    return unit_report(units, patches, buildings.to_crs(units.crs), newest("osm_green_"), names,
                       cfg.sampling.grid_step_m)


def explore_official(cfg, data_dir, max_values: int = 25) -> None:
    """Print what is inside each official polygon file: layers, columns and the area of every category (clipped to the city)."""
    from .ckan import CkanClient
    from .geo import read_geo_bytes, unary
    from .http import download_bytes
    from .sources import barcelona

    client = CkanClient(cfg.sources.ckan_base)
    cache = Path(data_dir) / "cache" / cfg.city.slug
    units = barcelona.load_boundaries(client, cfg, cache, {})
    city = unary(units.geometry)
    for src in cfg.sources.official_polygons:
        pkg = client.resolve_package([src.package], src.label)
        row = client.pick(pkg, tuple(src.formats), name_contains=src.name_contains or None)
        g = read_geo_bytes(download_bytes(row["url"], client.session), cache, cfg.city.crs_wgs84, cfg.city.crs_proj)
        g = g.to_crs(cfg.city.crs_proj).reset_index(drop=True)
        print(f"\n{'=' * 100}\n{src.label}  |  package {pkg}  |  file {row['name']}\n{'=' * 100}")
        for lay in (g["_layer"].unique() if "_layer" in g else [None]):
            d = g if lay is None else g[g["_layer"] == lay]
            polys = d[d.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
            inside = unary(polys.geometry).intersection(city).area / 1e6 if len(polys) else 0
            print(f"\nLAYER {lay!r}: {len(d)} features, {len(polys)} polygons, {inside:.2f} km2 inside the city")
            cols = [c for c in d.columns if c not in ("geometry", "_layer")]
            print("  columns:", cols)
            for c in cols:
                nun = d[c].astype(str).nunique()
                if nun > max_values:
                    print(f"  - {c}: {nun} distinct values (not listed)")
                    continue
                polys["_v"] = polys[c].astype(str)
                table = sorted(((v, len(grp), unary(grp.geometry).intersection(city).area / 1e6)
                                for v, grp in polys.groupby("_v")), key=lambda t: -t[2])
                print(f"  - {c}:")
                for v, n, a in table:
                    print(f"        {v[:60]:<60} {n:>6} polygons {a:>8.2f} km2 in city")
