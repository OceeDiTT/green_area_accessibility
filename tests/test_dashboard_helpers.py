import pandas as pd
import pytest
from greenspace.dashboard.helpers import (checks_headline, filter_ranking, fmt_dt, fmt_duration, green_layer_summary,
                                          map_view, quality_table, source_rows)


def _df():
    return pd.DataFrame({"district": ["A", "A", "B", "C"], "access_tier": ["Low", "High", "Low", "High"], "barri": list("wxyz")})


def test_filter_ranking_empty_selection_means_no_filter():
    assert len(filter_ranking(_df())) == 4                     # this was the crash: df[True] -> KeyError
    assert len(filter_ranking(_df(), [], [])) == 4
    assert list(filter_ranking(_df(), ["A"], [])["barri"]) == ["w", "x"]
    assert list(filter_ranking(_df(), [], ["High"])["barri"]) == ["x", "z"]
    assert list(filter_ranking(_df(), ["A"], ["High"])["barri"]) == ["x"]
    assert filter_ranking(_df(), ["B"], ["High"]).empty


def test_fmt_dt_and_duration():
    assert fmt_dt("2026-11-03T00:01:22+00:00") == "03 Nov 2026, 00:01 UTC"
    assert fmt_dt("2026-11-03T00:01:22+00:00", with_time=False) == "03 Nov 2026"
    assert fmt_dt(None) == "–" and fmt_dt("garbage") == "–"
    assert fmt_duration(497.3) == "8 min 17 s" and fmt_duration(42) == "42 s" and fmt_duration(None) == "–"


def test_checks_headline():
    assert checks_headline({"pass": 19, "warn": 0, "fail": 0}) == "✅ All 19 quality checks passed"
    assert "1 warning" in checks_headline({"pass": 18, "warn": 1, "fail": 0}) and "warnings" not in checks_headline({"pass": 18, "warn": 1})
    assert checks_headline({"pass": 3, "warn": 2, "fail": 1}).startswith("❌")
    assert checks_headline(None).startswith("✅")


def test_map_view_fits_barcelona_extent():
    ring = [[2.05, 41.32], [2.23, 41.32], [2.23, 41.47], [2.05, 41.47], [2.05, 41.32]]
    gj = {"features": [{"geometry": {"type": "Polygon", "coordinates": [ring]}}]}
    v = map_view(gj)
    assert v["center"]["lat"] == pytest.approx(41.395) and v["center"]["lon"] == pytest.approx(2.14)
    assert 10.3 < v["zoom"] < 11.5
    assert map_view({"features": []})["zoom"] == 10.5


def test_quality_table_orders_by_severity_and_uses_plain_labels():
    q = quality_table([{"name": "unit_count", "status": "pass", "detail": "73 units"},
                       {"name": "exclusion_zone", "status": "fail", "detail": "missing"},
                       {"name": "register_match", "status": "warn", "detail": "60 %"},
                       {"name": "brand_new_check", "status": "pass", "detail": "x"}])
    assert list(q["Result"]) == ["❌ Fail", "⚠️ Warning", "✅ Pass", "✅ Pass"]
    assert q.loc[0, "Check"] == "Collserola natural park excluded" and "Brand new check" in list(q["Check"])
    assert list(quality_table([]).columns) == ["Result", "Check", "Details"]


def test_source_rows_handles_real_and_partial_metadata():
    src = {"boundaries": {"package": "p", "resource": "BarcelonaCiutat_Barris.csv"},
           "income": {"resource": "2023_renda.csv", "reference_year": 2023},
           "population": {"resource": "2024_pad_mdbas.csv", "reference_year": 2024},
           "osm_green": {"api": "Overpass"},
           "official_polygons": {"public_green_over_half_ha": {"resource": "2019_pev_parcs_od.gpkg", "polygons_in_file": 190, "polygons_kept": 188},
                                 "broken": {"error": "boom"}},
           "exclusion_zone": {"features": ["Parc Natural de la Serra de Collserola"]},
           "stations": {"api": "Overpass"}, "resident_sampling": {"method": "buildings", "points": 66095},
           "register": {"resource": "parks.csv"}}
    r = source_rows(src)
    assert len(r) == 10 and set(r["Licence"]) == {"CC BY 4.0", "ODbL"}
    assert "188 of 190 polygons used" in " ".join(r["Dataset"]) and "66,095" in " ".join(r["Dataset"])
    assert "2019" in list(r.loc[r["Layer"] == "Parks > 0.5 ha (city)", "Reference"])
    assert list(source_rows({}).columns) == ["Layer", "Provider", "Dataset", "Reference", "Licence"] and source_rows(None).empty


def test_green_layer_summary():
    s = green_layer_summary({"final_km2": 10.53, "osm_km2": 10.06, "official_km2": 4.45, "excluded_km2": 0.0265})
    assert s[0][:2] == ("Green space used", "10.53 km²") and s[3][1] == "0.03 km²"
    assert green_layer_summary(None)[0][1] == "–"
