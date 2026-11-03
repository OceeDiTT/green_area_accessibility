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


def _grid_points(units, step: float) -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = units.total_bounds
    xx, yy = np.meshgrid(np.arange(minx + step / 2, maxx, step), np.arange(miny + step / 2, maxy, step))
    return gpd.GeoDataFrame({"w": np.ones(xx.size)}, geometry=gpd.points_from_xy(xx.ravel(), yy.ravel()), crs=units.crs)


def _locate(pts, units, green_union):
    """Assign points to units; nobody lives inside a park."""
    pts = gpd.sjoin(pts[["w", "geometry"]], units[["barri_code", "geometry"]], predicate="within", how="inner")
    pts = pts.drop(columns="index_right")
    inside_green = shapely.intersects(np.asarray(pts.geometry.values), green_union)
    return pts[~inside_green].reset_index(drop=True)


def sample_points(units, green_union, cfg: CityConfig, buildings_loader):
    """Where do residents live? Building centroids weighted by footprint (column src='building').

    Units that end up with no building point (data gaps, or buildings only inside parks) are filled with a regular
    grid *for those units only* (src='grid') instead of being scored as if nobody could reach any green space.
    """
    method = cfg.sampling.method
    step = cfg.sampling.grid_step_m
    raw = None
    if method == "buildings":
        try:
            raw = buildings_loader().to_crs(units.crs)
        except Exception as e:
            reason = (str(e).strip().splitlines() or [""])[0][:200]
            if not cfg.sampling.allow_grid_fallback:
                raise RuntimeError(
                    f"Building footprints unavailable ({type(e).__name__}: {reason}). Retry later, or set "
                    "sampling.allow_grid_fallback: true (uniform grid, less accurate) in the config.") from e
            log.warning("buildings unavailable (%s: %s) - using grid sampling (allow_grid_fallback)", type(e).__name__, reason)
            method = "grid"
    if raw is None:
        pts = _locate(_grid_points(units, step), units, green_union)
        pts["src"] = "grid"
        return pts, method
    pts = _locate(raw, units, green_union)
    pts["src"] = "building"
    missing = sorted(set(units["barri_code"]) - set(pts["barri_code"]))
    if missing:
        fill = _locate(_grid_points(units[units["barri_code"].isin(missing)], step), units[units["barri_code"].isin(missing)], green_union)
        fill["src"] = "grid"
        log.warning("%d unit(s) have no building footprints - using grid points there: %s", len(missing), missing)
        pts = gpd.GeoDataFrame(pd.concat([pts, fill], ignore_index=True), crs=units.crs)
    return pts, method


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


def natural_park_shares(points, exclusion, dist_m: float) -> pd.DataFrame:
    """Context indicator: share of each unit's residents within dist_m of the excluded natural park (e.g. Collserola)."""
    if exclusion is None or len(exclusion) == 0:
        return pd.DataFrame({"barri_code": sorted(points["barri_code"].unique()), "natural_park_share": 0.0})
    buf = unary(exclusion.geometry).buffer(dist_m)
    shapely.prepare(buf)
    p = points.copy()
    p["near"] = shapely.intersects(np.asarray(p.geometry.values), buf)
    tot = p.groupby("barri_code")["w"].sum()
    return ((p["near"] * p["w"]).groupby(p["barri_code"]).sum() / tot).rename("natural_park_share").reset_index()
