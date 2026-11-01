"""End-to-end orchestration: ingest -> hybrid green layer -> metrics -> score -> validate -> publish."""
import hashlib
import importlib
import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import CityConfig, to_dict
from .schema import EXPORT_COLS
from .scoring import score_frame
from .stats import city_stats, district_summary
from .store import RunStore
from .validate import has_failures, run_checks, summarize

log = logging.getLogger(__name__)

ADAPTERS = {"barcelona_ckan": "greenspace.sources.barcelona"}


class PipelineError(RuntimeError):
    def __init__(self, message, checks=None):
        super().__init__(message)
        self.checks = checks or []


def _h(obj) -> str:
    """Short hash so cached API results are invalidated when the query parameters change."""
    return hashlib.md5(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:8]


@contextmanager
def _step(timings: list, name: str):
    t0 = time.perf_counter()
    log.info(">> %s", name)
    try:
        yield
    finally:
        timings.append({"step": name, "seconds": round(time.perf_counter() - t0, 1)})


def _write_artifacts(run_dir: Path, b, green, stations, districts, cfg: CityConfig, metadata: dict, checks: list):
    import geopandas as gpd  # noqa: F401  (ensures the pipeline extra is installed)
    wgs = cfg.city.crs_wgs84
    tab = b[EXPORT_COLS].copy()
    tab.to_csv(run_dir / "barris.csv", index=False)
    districts.to_csv(run_dir / "districts.csv", index=False)

    g = b[EXPORT_COLS + ["geometry"]].copy()
    g["geometry"] = g.geometry.simplify(5, preserve_topology=True)
    g.to_crs(wgs).to_file(run_dir / "barris.geojson", driver="GeoJSON")

    p = green.patches[green.patches["area_m2"] >= 1000].copy()
    p["geometry"] = p.geometry.simplify(2, preserve_topology=True)
    p.to_crs(wgs).to_file(run_dir / "green_patches.geojson", driver="GeoJSON")
    if stations is not None and len(stations):
        stations.to_crs(wgs).to_file(run_dir / "stations.geojson", driver="GeoJSON")

    gpkg = run_dir / "green_metrics.gpkg"                    # full-precision layers for GIS users
    b[EXPORT_COLS + ["geometry"]].to_file(gpkg, layer="units", driver="GPKG")
    green.patches.to_file(gpkg, layer="green_patches", driver="GPKG")

    (run_dir / "checks.json").write_text(json.dumps([c.to_dict() for c in checks], indent=2), encoding="utf-8")
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")


def run_pipeline(cfg: CityConfig, data_dir="data", refresh: bool = False, force: bool = False) -> dict:
    """Run the full pipeline. Publishes (atomically) only if all quality checks pass, unless force=True."""
    from .ckan import CkanClient
    from .geo import Cache, unary
    from .green import build_green, register_match_rate
    from .metrics import proximity_shares, sample_points, unit_metrics
    from .sources import osm

    adapter = importlib.import_module(ADAPTERS[cfg.city.adapter])
    store = RunStore(data_dir, cfg.city.slug)
    run_id, run_dir = store.begin()
    started = datetime.now(timezone.utc)
    prov: dict = {}
    timings: list = []
    crs = cfg.city.crs_proj
    cache = Cache(Path(data_dir) / "cache" / cfg.city.slug, refresh, cfg.runtime.cache_max_age_days)
    client = CkanClient(cfg.sources.ckan_base)
    log.info("Run %s for %s (greenspace %s)", run_id, cfg.city.name, __version__)

    try:
        with _step(timings, "boundaries"):
            units = adapter.load_boundaries(client, cfg, cache.root, prov)
        with _step(timings, "income"):
            inc = adapter.load_income(client, cfg, prov)
        with _step(timings, "population"):
            pop = adapter.load_population(client, cfg, prov, target_year=prov["income"].get("reference_year"))

        osm.configure(cfg.sources.overpass_endpoints)
        city_poly = unary(units.geometry)
        qpoly = osm.query_polygon(units, cfg.city.crs_wgs84)

        osm_green = None
        if cfg.green.use_osm:
            with _step(timings, "osm_green"):
                osm_green = cache.gdf(f"osm_green_{_h(cfg.green.osm_tags)}",
                                      lambda: osm.fetch_green(qpoly, cfg.green.osm_tags, crs))
            prov["osm_green"] = {"api": "Overpass (OpenStreetMap)", "tags": cfg.green.osm_tags, "licence": "ODbL"}
        official = {}
        if cfg.green.use_official:
            with _step(timings, "official_green"):
                official = adapter.load_official_polygons(client, cfg, cache.root, prov)

        excl = None
        ex = cfg.green.exclusion
        if ex.name_patterns:
            with _step(timings, "exclusion_zone"):
                excl = cache.gdf(f"exclusion_{_h([ex.name_patterns, ex.osm_tags])}",
                                 lambda: osm.fetch_exclusion_zone(qpoly, ex.name_patterns, ex.osm_tags, crs))
            prov["exclusion_zone"] = {"patterns": ex.name_patterns,
                                      "features": [] if excl is None or not len(excl) else excl["name"].tolist()}

        with _step(timings, "green_layer"):
            green = build_green(osm_green, official, excl, city_poly, cfg.green.min_green_m2, crs)
        log.info("green layer: %s", {k: (round(v, 2) if isinstance(v, float) else v) for k, v in green.report.items()
                                     if not isinstance(v, dict)})

        with _step(timings, "register_crosscheck"):
            match = register_match_rate(adapter.load_register_points(client, cfg, prov), green.union,
                                        cfg.green.register_tolerance_m)

        stations = None
        try:
            with _step(timings, "stations"):
                stations = cache.gdf("osm_stations", lambda: osm.fetch_stations(qpoly, crs))
            prov["stations"] = {"api": "Overpass (OpenStreetMap)", "tags": {"railway": ["station"]}}
        except Exception as e:                                           # informational layer, not critical
            log.warning("stations unavailable: %s", e)

        with _step(timings, "unit_metrics"):
            b = unit_metrics(units, pop, inc, green.union, stations, cfg)
        with _step(timings, "proximity"):
            pts, method = sample_points(
                units, green.union, cfg,
                lambda: cache.gdf(f"osm_buildings_{_h(cfg.sampling.min_building_m2)}",
                                  lambda: osm.fetch_buildings(qpoly, cfg.sampling.min_building_m2, crs)))
            prox = proximity_shares(pts, green.patches, cfg)
            b = b.merge(prox, on="barri_code", how="left")
            b[["share_300m_05ha", "share_1km_5ha"]] = b[["share_300m_05ha", "share_1km_5ha"]].fillna(0)
        name_of = dict(zip(b["barri_code"], b["barri"]))
        grid_filled = sorted(name_of[c] for c in set(pts.loc[pts["src"] == "grid", "barri_code"])) if method == "buildings" else []
        no_points = sorted(name_of[c] for c in set(b["barri_code"]) - set(pts["barri_code"]))
        prov["resident_sampling"] = {"method": method, "points": int(len(pts)), "grid_filled_units": grid_filled,
                                     "units_without_points": no_points}

        with _step(timings, "scoring"):
            b = score_frame(b, cfg)
            stats = city_stats(b, cfg)
            districts = district_summary(b)

        with _step(timings, "validation"):
            ctx = {"population_year": prov["population"].get("reference_year"),
                   "income_year": prov["income"].get("reference_year"),
                   "register_match_rate": match,
                   "exclusion_zone_found": green.report["exclusion_zone_found"],
                   "official_km2": green.report["official_km2"],
                   "n_points": len(pts), "points_method": method,
                   "units_without_points": no_points, "units_grid_filled": grid_filled}
            checks = run_checks(b, ctx, cfg, previous=store.load_table())
        for c in checks:
            if c.status != "pass":
                log.log(logging.ERROR if c.status == "fail" else logging.WARNING, "check %s [%s]: %s", c.name, c.status, c.detail)

        finished = datetime.now(timezone.utc)
        failed = has_failures(checks)
        metadata = {
            "run_id": run_id, "city": cfg.city.name, "slug": cfg.city.slug, "software_version": __version__,
            "status": "rejected" if failed else "published",
            "started_utc": started.isoformat(timespec="seconds"), "finished_utc": finished.isoformat(timespec="seconds"),
            "duration_s": round((finished - started).total_seconds(), 1), "steps": timings,
            "checks_summary": summarize(checks), "stats": stats, "green_layer": green.report,
            "sources": prov, "config": to_dict(cfg),
            "attribution": ["Ajuntament de Barcelona - Open Data BCN (CC BY 4.0)",
                            "(c) OpenStreetMap contributors (ODbL)"],
        }
        _write_artifacts(run_dir, b, green, stations, districts, cfg, metadata, checks)

        if failed and not force:
            store.fail(run_id)
            raise PipelineError(f"Run {run_id} rejected by quality checks: "
                                + "; ".join(f"{c.name}: {c.detail}" for c in checks if c.status == "fail"), checks)
        store.commit(run_id)
        removed = store.prune(cfg.runtime.keep_runs)
        log.info("Run %s %s (%s). Pruned: %s", run_id, "PUBLISHED" if not failed else "FORCED", summarize(checks), removed)
        return {"run_id": run_id, "status": metadata["status"], "checks": summarize(checks), "path": str(store.path(run_id))}
    except PipelineError:
        raise
    except Exception as e:
        log.exception("Run %s crashed", run_id)
        try:
            (run_dir / "error.txt").write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
            store.fail(run_id)
        except Exception:
            pass
        raise PipelineError(f"Run {run_id} crashed: {type(e).__name__}: {e}") from e
