"""Barcelona adapter: Open Data BCN (CKAN) for boundaries, population, income and the official green layers."""
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from ..ckan import CkanClient
from ..config import CityConfig
from ..geo import read_geo_bytes, valid
from ..http import download_bytes
from ..tabular import filter_features, find_col, latest_by_unit, norm

log = logging.getLogger(__name__)


def load_boundaries(client: CkanClient, cfg: CityConfig, workdir: Path, prov: dict) -> gpd.GeoDataFrame:
    pkg = client.resolve_package(cfg.sources.boundaries, "districtes barris limits administratius")
    res = client.list_resources(pkg)
    cand = res[res["name"].map(norm).str.contains("barri") | res["url"].map(norm).str.contains("barri")]
    if cand.empty:
        raise RuntimeError(f"No 'barri' boundary resource in package {pkg}: {res.to_dict('records')}")
    g, row = None, None
    for _, r in cand[cand["format"].isin(["geojson", "json", "gpkg", "zip", "shp", "shz"])].iterrows():
        try:
            g = read_geo_bytes(download_bytes(r["url"], client.session), workdir, cfg.city.crs_wgs84, cfg.city.crs_proj)
            row = r
            break
        except Exception as e:
            log.warning("skipping boundary resource '%s': %s: %s", r["name"], type(e).__name__, e)
    if g is None:                                          # CSV with a WKT geometry column
        row = client.pick(pkg, ("csv",), name_contains="barri")
        df = client.read_table(row)
        wkt = find_col(df, ["geometria_wgs84", "geometry_wgs84", "wkt", "geometry", "geometria", "geometria_etrs89"])
        crs = cfg.city.crs_proj if "etrs89" in norm(wkt) else cfg.city.crs_wgs84
        g = gpd.GeoDataFrame(df.drop(columns=[wkt]), geometry=gpd.GeoSeries.from_wkt(df[wkt]), crs=crs)
    prov["boundaries"] = {"package": pkg, "resource": row["name"], "url": row["url"]}
    code_col, name_col = find_col(g, ["codi_barri", "barri", "codi"]), find_col(g, ["nom_barri", "nom"])
    dist_col = find_col(g, ["nom_districte", "districte"], required=False)
    out = gpd.GeoDataFrame({
        "barri_code": pd.to_numeric(g[code_col], errors="coerce"),
        "barri": g[name_col].astype(str).values,
        "district": g[dist_col].astype(str).values if dist_col else "",
        "geometry": g.geometry.values}, crs=g.crs).dropna(subset=["barri_code"])
    out["barri_code"] = out["barri_code"].astype("int64")
    return valid(out.to_crs(cfg.city.crs_proj)).reset_index(drop=True)


def load_income(client: CkanClient, cfg: CityConfig, prov: dict) -> pd.DataFrame:
    pkg = client.resolve_package(cfg.sources.income, "renda disponible llars barris")
    row = client.pick(pkg, ("csv",))
    df = client.read_table(row)
    code_c = find_col(df, ["codi_barri", "barri"])
    val_c = find_col(df, ["import_euros", "import", "renda", "valor", "index"])
    year_c = find_col(df, ["any", "year"], required=False)
    out, year = latest_by_unit(df, code_c, val_c, year_c, agg="mean")
    prov["income"] = {"package": pkg, "resource": row["name"], "url": row["url"], "value_column": val_c, "reference_year": year}
    return out.rename(columns={"_v": "income_eur_pc"})


def load_population(client: CkanClient, cfg: CityConfig, prov: dict, target_year=None) -> pd.DataFrame:
    pkg = client.resolve_package(cfg.sources.population, "padro poblacio barris")
    row = client.pick(pkg, ("csv",), target_year=target_year)
    df = client.read_table(row)
    code_c = find_col(df, ["codi_barri", "barri"])
    val_c = find_col(df, ["valor", "poblacio", "nombre", "habitants", "total"])
    year_c = find_col(df, ["any", "year", "data_referencia"], required=False)
    out, year = latest_by_unit(df, code_c, val_c, year_c, agg="sum")
    prov["population"] = {"package": pkg, "resource": row["name"], "url": row["url"], "reference_year": year}
    return out.rename(columns={"_v": "population"})


def load_register_points(client: CkanClient, cfg: CityConfig, prov: dict):
    """Official parks & gardens register (points). Used for QA of the green layer, not for area."""
    try:
        pkg = client.resolve_package(cfg.sources.register, "parcs i jardins")
        row = client.pick(pkg, ("csv",))
        df = client.read_table(row)
        lat = find_col(df, ["geo_epgs_4326_lat", "geo_epgs_4326_y", "latitud", "lat"])
        lon = find_col(df, ["geo_epgs_4326_lon", "geo_epgs_4326_x", "longitud", "lon"])
        df[lat], df[lon] = pd.to_numeric(df[lat], errors="coerce"), pd.to_numeric(df[lon], errors="coerce")
        df = df.dropna(subset=[lat, lon])
        prov["register"] = {"package": pkg, "resource": row["name"], "url": row["url"], "n_points": int(len(df))}
        return gpd.GeoDataFrame(df[[]].copy(), geometry=gpd.points_from_xy(df[lon], df[lat]),
                                crs=cfg.city.crs_wgs84).to_crs(cfg.city.crs_proj)
    except Exception as e:
        log.warning("park register unavailable: %s: %s", type(e).__name__, e)
        prov["register"] = {"error": f"{type(e).__name__}: {e}"}
        return None


def load_official_polygons(client: CkanClient, cfg: CityConfig, workdir: Path, prov: dict) -> dict:
    """City-published green-space polygons (GeoPackage). A failing layer is skipped and recorded, not fatal."""
    out, info = {}, {}
    for src in cfg.sources.official_polygons:
        try:
            pkg = client.resolve_package([src.package], src.label)
            row = client.pick(pkg, tuple(src.formats), name_contains=src.name_contains or None)
            g = read_geo_bytes(download_bytes(row["url"], client.session), workdir, cfg.city.crs_wgs84, cfg.city.crs_proj)
            g = g[g.geom_type.isin(["Polygon", "MultiPolygon"])]
            n_raw = int(len(g))
            g = filter_features(g, src.layers, src.where, src.exclude)[["geometry"]]
            out[src.label] = valid(g.to_crs(cfg.city.crs_proj)).reset_index(drop=True)
            log.info("official layer '%s': kept %d of %d polygons (layers=%s where=%s exclude=%s)",
                     src.label, len(g), n_raw, src.layers or "all", src.where or "-", src.exclude or "-")
            info[src.label] = {"package": pkg, "resource": row["name"], "url": row["url"], "polygons_in_file": n_raw,
                               "polygons_kept": int(len(g)), "filters": {"layers": src.layers, "where": src.where, "exclude": src.exclude}}
        except Exception as e:
            log.warning("official layer '%s' skipped: %s: %s", src.label, type(e).__name__, e)
            info[src.label] = {"error": f"{type(e).__name__}: {e}"}
    prov["official_polygons"] = info
    return out
