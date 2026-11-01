"""Per-unit spatial metrics: supply (area, per-capita) and proximity (share of residents within reach)."""
import logging

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from .config import CityConfig
from .geo import unary

log = logging.getLogger(__name__)


def unit_metrics(units, pop, inc, green_union, stations, cfg: CityConfig) -> gpd.GeoDataFrame:
    b = units.merge(pop, on="barri_code", how="left").merge(inc, on="barri_code", how="left")
    b["area_m2"] = b.geometry.area
    b["green_m2"] = b.geometry.intersection(green_union).area
    b["green_cover_pct"] = b["green_m2"] / b["area_m2"] * 100
    b["pop_density_km2"] = b["population"] / (b["area_m2"] / 1e6)
    b["green_m2_pp"] = b["green_m2"] / b["population"]
    b["people_per_1000m2_green"] = np.where(b["green_m2"] > 0, b["population"] / (b["green_m2"] / 1000), np.nan)
    ok = b["income_eur_pc"].notna() & b["population"].notna()
    city_mean = np.average(b.loc[ok, "income_eur_pc"], weights=b.loc[ok, "population"])
    b["rfd_index"] = b["income_eur_pc"] / city_mean * 100
    b["low_income"] = b["rfd_index"] < cfg.equity.low_income_index
    if stations is not None and len(stations):
        st = gpd.sjoin(stations, b[["barri_code", "geometry"]], predicate="within", how="inner")
        cnt = st.groupby("barri_code").size().rename("n_stations").reset_index()
        b = b.merge(cnt, on="barri_code", how="left")
    else:
        b["n_stations"] = 0
    b["n_stations"] = b["n_stations"].fillna(0).astype(int)
    return b


def sample_points(units, green_union, cfg: CityConfig, buildings_loader):
    """Where do residents live? Building centroids weighted by footprint; falls back to a regular grid."""
    method = cfg.sampling.method
    pts = None
    if method == "buildings":
        try:
            pts = buildings_loader().to_crs(units.crs)
        except Exception as e:
            log.warning("buildings unavailable (%s: %s) - falling back to grid sampling", type(e).__name__, e)
            method = "grid"
    if pts is None:
        step = cfg.sampling.grid_step_m
        minx, miny, maxx, maxy = units.total_bounds
        xx, yy = np.meshgrid(np.arange(minx + step / 2, maxx, step), np.arange(miny + step / 2, maxy, step))
        pts = gpd.GeoDataFrame({"w": 1.0}, geometry=gpd.points_from_xy(xx.ravel(), yy.ravel()), crs=units.crs)
    pts = gpd.sjoin(pts[["w", "geometry"]], units[["barri_code", "geometry"]], predicate="within", how="inner")
    pts = pts.drop(columns="index_right")
    inside_green = shapely.intersects(np.asarray(pts.geometry.values), green_union)    # nobody lives inside a park
    return pts[~inside_green].reset_index(drop=True), method


def _reach(points, patches, min_area, dist):
    sel = patches[patches["area_m2"] >= min_area]
    if sel.empty:
        return np.zeros(len(points), dtype=bool)
    buf = unary(sel.geometry.buffer(dist))
    shapely.prepare(buf)
    return shapely.intersects(np.asarray(points.geometry.values), buf)


def proximity_shares(points, patches, cfg: CityConfig) -> pd.DataFrame:
    st = cfg.standards
    p = points.copy()
    p["near_small"] = _reach(p, patches, st.near_min_m2, st.near_dist_m)
    p["near_large"] = _reach(p, patches, st.large_min_m2, st.large_dist_m)
    tot = p.groupby("barri_code")["w"].sum()

    def share(flag):
        return (p[flag] * p["w"]).groupby(p["barri_code"]).sum() / tot

    return pd.DataFrame({"share_300m_05ha": share("near_small"), "share_1km_5ha": share("near_large")}).reset_index()
