"""Geospatial logic on tiny synthetic geometries (metres). Skipped unless the 'pipeline' extra is installed."""
import pytest

pytest.importorskip("geopandas")
pytest.importorskip("shapely")
import geopandas as gpd  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry import GeometryCollection, LineString, Point, box  # noqa: E402

from greenspace.geo import polygonal  # noqa: E402
from greenspace.green import build_green, register_match_rate  # noqa: E402
from greenspace.metrics import proximity_shares, sample_points, unit_metrics  # noqa: E402
from helpers import make_cfg  # noqa: E402

CRS = "EPSG:25831"


def _g(*geoms):
    return gpd.GeoDataFrame(geometry=list(geoms), crs=CRS)


def test_polygonal_drops_lines():
    gc = GeometryCollection([LineString([(0, 0), (1, 1)]), box(0, 0, 2, 2)])
    assert polygonal(gc).area == 4 and polygonal(LineString([(0, 0), (1, 1)])).is_empty


def test_hybrid_union_has_no_double_counting_and_exclusion_removes_area():
    city = box(0, 0, 200, 100)
    osm = _g(box(0, 0, 100, 100))
    official = {"a": _g(box(50, 0, 150, 100))}          # overlaps OSM by half
    excl = _g(box(120, 0, 200, 100))                    # the "Collserola" zone
    r = build_green(osm, official, excl, city, 100, CRS)
    rep = r.report
    assert rep["osm_km2"] == pytest.approx(0.01) and rep["official_km2"] == pytest.approx(0.01)
    assert rep["combined_before_exclusion_km2"] == pytest.approx(0.015)        # 150 x 100, overlap counted once
    assert rep["excluded_km2"] == pytest.approx(0.003)                         # 30 x 100 removed
    assert rep["final_km2"] == pytest.approx(0.012)
    assert rep["official_share_also_in_osm"] == pytest.approx(0.5)
    assert rep["exclusion_zone_found"] and not r.union.intersects(box(121, 1, 199, 99))


def test_without_exclusion_zone_is_reported():
    r = build_green(_g(box(0, 0, 100, 100)), {}, None, box(0, 0, 200, 100), 100, CRS)
    assert not r.report["exclusion_zone_found"] and r.report["final_km2"] == pytest.approx(0.01)


def test_slivers_dropped():
    r = build_green(_g(box(0, 0, 100, 100), box(150, 0, 155, 5)), {}, None, box(0, 0, 200, 100), 100, CRS)
    assert len(r.patches) == 1


def test_register_match_rate():
    union = box(0, 0, 100, 100)
    pts = _g(Point(10, 10), Point(500, 500))
    assert register_match_rate(pts, union, 50) == pytest.approx(0.5)
    assert register_match_rate(None, union, 50) is None


def test_proximity_shares():
    cfg = make_cfg()
    patches = _g(box(0, 0, 100, 100))
    patches["area_m2"] = patches.geometry.area                     # 10,000 m2: counts as >=0.5 ha, not as >=5 ha
    pts = gpd.GeoDataFrame({"w": [1.0, 1.0], "barri_code": [1, 1]}, geometry=[Point(50, 250), Point(900, 900)], crs=CRS)
    out = proximity_shares(pts, patches, cfg).iloc[0]
    assert out["share_300m_05ha"] == pytest.approx(0.5) and out["share_1km_5ha"] == 0


def test_unit_metrics_basics():
    cfg = make_cfg()
    units = gpd.GeoDataFrame({"barri_code": [1, 2], "barri": ["A", "B"], "district": ["D", "D"]},
                             geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100)], crs=CRS)
    import pandas as pd
    pop = pd.DataFrame({"barri_code": [1, 2], "population": [1000.0, 1000.0]})
    inc = pd.DataFrame({"barri_code": [1, 2], "income_eur_pc": [10000.0, 30000.0]})
    b = unit_metrics(units, pop, inc, box(0, 0, 50, 100), None, cfg)
    assert b.loc[0, "green_m2"] == pytest.approx(5000) and b.loc[0, "green_cover_pct"] == pytest.approx(50)
    assert b.loc[1, "green_m2"] == 0
    assert b["rfd_index"].tolist() == pytest.approx([50, 150]) and b["low_income"].tolist() == [True, False]


def _units():
    return gpd.GeoDataFrame({"barri_code": [1], "barri": ["A"], "district": ["D"]}, geometry=[box(0, 0, 1000, 1000)], crs=CRS)


def _boom():
    raise ConnectionError("502 Bad Gateway")


def test_grid_sampling_builds_and_excludes_parks():
    cfg = make_cfg(sampling={"method": "grid", "grid_step_m": 100})
    pts, method = sample_points(_units(), box(0, 0, 100, 100), cfg, _boom)
    assert method == "grid" and len(pts) == 99                     # 10 x 10 grid minus the cell inside the park
    assert (pts["w"] == 1.0).all() and (pts["barri_code"] == 1).all()


def test_building_failure_is_an_error_unless_fallback_allowed():
    strict = make_cfg(sampling={"method": "buildings", "grid_step_m": 100})
    with pytest.raises(RuntimeError):
        sample_points(_units(), box(0, 0, 100, 100), strict, _boom)
    lenient = make_cfg(sampling={"method": "buildings", "grid_step_m": 100, "allow_grid_fallback": True})
    pts, method = sample_points(_units(), box(0, 0, 100, 100), lenient, _boom)
    assert method == "grid" and len(pts) == 99


def test_building_sampling_uses_footprint_weights():
    cfg = make_cfg()
    blds = gpd.GeoDataFrame({"w": [100.0, 300.0, 50.0]}, geometry=[Point(500, 500), Point(600, 600), Point(50, 50)], crs=CRS)
    pts, method = sample_points(_units(), box(0, 0, 100, 100), cfg, lambda: blds)
    assert method == "buildings" and sorted(pts["w"]) == [100.0, 300.0]       # the building inside the park is dropped


def test_units_without_buildings_are_filled_with_grid_points():
    cfg = make_cfg(sampling={"method": "buildings", "grid_step_m": 500})
    units = gpd.GeoDataFrame({"barri_code": [1, 2], "barri": ["A", "B"], "district": ["D", "D"]},
                             geometry=[box(0, 0, 1000, 1000), box(1000, 0, 2000, 1000)], crs=CRS)
    blds = gpd.GeoDataFrame({"w": [100.0, 200.0]}, geometry=[Point(300, 300), Point(700, 700)], crs=CRS)   # only in unit A
    pts, method = sample_points(units, box(5000, 5000, 5001, 5001), cfg, lambda: blds)
    assert method == "buildings" and set(pts["barri_code"]) == {1, 2}
    assert (pts.loc[pts["src"] == "building", "barri_code"] == 1).all()
    grid = pts[pts["src"] == "grid"]
    assert len(grid) == 4 and (grid["barri_code"] == 2).all() and (grid["w"] == 1.0).all()


def test_inspect_report_counts_buildings_and_green_sources():
    from greenspace.diagnose import unit_report
    units = gpd.GeoDataFrame({"barri": ["Old Town"], "green_cover_pct": [10.0]}, geometry=[box(0, 0, 1000, 1000)], crs=CRS)
    patches = _g(box(0, 0, 200, 200), box(800, 0, 1000, 200))             # city green layer (two patches)
    osm = _g(box(0, 0, 200, 200))                                           # only the first one is in OSM
    blds = gpd.GeoDataFrame({"w": [1.0] * 4}, geometry=[Point(100, 100), Point(900, 100), Point(500, 500), Point(600, 600)], crs=CRS)
    r = unit_report(units, patches, blds, osm, ["old town"], grid_step=100).iloc[0]
    assert r["buildings"] == 4 and r["in_green_layer"] == 2 and r["of_which_in_OSM_green"] == 1 and r["buildings_kept"] == 2
    assert r["grid_points"] == 100 and r["grid_points_outside_green"] == 100 - 8      # two 2x2-cell patches
