"""Pure presentation helpers for the dashboard (no streamlit import, so they are unit-testable)."""
import math
import re
from datetime import datetime

import pandas as pd

CHECK_LABELS = {
    "unit_count": "Number of barris", "unique_codes": "Unique barri codes", "population_complete": "Population available for every barri",
    "population_total": "City population plausible", "income_coverage": "Income data coverage", "reference_year_gap": "Population / income reference years",
    "city_green_cover": "City-wide green coverage plausible", "unit_cover_bounds": "Green coverage within 0–100 % per barri",
    "unit_cover_sane": "No barri with implausible green coverage", "unit_cover_plausible": "No barri with unusually high green coverage",
    "score_valid": "Scores valid (0–100)", "register_match": "Agreement with the city park register",
    "exclusion_zone": "Collserola natural park excluded", "official_polygons": "Official park polygons loaded",
    "sampling_method": "Resident sampling method", "sample_points": "Resident sample points", "units_with_points": "Every barri has resident sample points",
    "units_grid_filled": "Barris without building footprints", "rank_drift": "Ranking stability vs previous run",
}
STATUS_ICON = {"pass": "✅ Pass", "warn": "⚠️ Warning", "fail": "❌ Fail"}
_SEVERITY = {"fail": 0, "warn": 1, "pass": 2}


def fmt_dt(iso, with_time: bool = True) -> str:
    try:
        d = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return "–"
    return d.strftime("%d %b %Y, %H:%M UTC") if with_time else d.strftime("%d %b %Y")


def fmt_duration(seconds) -> str:
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "–"
    return f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s"


def checks_headline(summary: dict | None) -> str:
    s = summary or {}
    w, f = s.get("warn", 0), s.get("fail", 0)
    if f:
        return f"❌ {f} quality check(s) failed"
    if w:
        return f"⚠️ {s.get('pass', 0)} checks passed · {w} warning{'s' if w != 1 else ''}"
    return f"✅ All {s.get('pass', 0)} quality checks passed"


def _flatten(coords, xs, ys):
    if coords and isinstance(coords[0], (int, float)):
        xs.append(coords[0])
        ys.append(coords[1])
    else:
        for c in coords:
            _flatten(c, xs, ys)


def map_view(gj: dict, width: int = 1100, height: int = 620) -> dict:
    """Centre and zoom that fit a GeoJSON FeatureCollection (web-mercator maths, 512 px tiles)."""
    xs, ys = [], []
    for f in gj.get("features", []):
        _flatten(f["geometry"]["coordinates"], xs, ys)
    if not xs:
        return {"center": {"lat": 41.39, "lon": 2.16}, "zoom": 10.5}
    lon_span, lat_span = max(max(xs) - min(xs), 1e-6), max(max(ys) - min(ys), 1e-6)
    lat_c = (max(ys) + min(ys)) / 2
    z_lon = math.log2(width * 360 / (512 * lon_span))
    z_lat = math.log2(height * 360 / (512 * lat_span / math.cos(math.radians(lat_c))))
    return {"center": {"lat": lat_c, "lon": (max(xs) + min(xs)) / 2}, "zoom": round(max(8.0, min(13.0, min(z_lon, z_lat) - 0.2)), 2)}


def filter_ranking(df: pd.DataFrame, districts=None, tiers=None) -> pd.DataFrame:
    """Empty selections mean 'no filter' (the original one-liner crashed with df[True])."""
    mask = pd.Series(True, index=df.index)
    if districts:
        mask &= df["district"].isin(districts)
    if tiers:
        mask &= df["access_tier"].isin(tiers)
    return df[mask]


def quality_table(checks: list[dict]) -> pd.DataFrame:
    if not checks:
        return pd.DataFrame(columns=["Result", "Check", "Details"])
    q = pd.DataFrame(checks)
    q["_s"] = q["status"].map(_SEVERITY).fillna(3)
    q = q.sort_values("_s", kind="stable")
    return pd.DataFrame({"Result": q["status"].map(STATUS_ICON).fillna(q["status"]),
                         "Check": q["name"].map(lambda n: CHECK_LABELS.get(n, n.replace("_", " ").capitalize())),
                         "Details": q["detail"]}).reset_index(drop=True)


def _year_in(text) -> str:
    m = re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", str(text or ""))
    return m.group(0) if m else "–"


def source_rows(src: dict | None) -> pd.DataFrame:
    """Readable table of every data source of a run (replaces the raw JSON dump)."""
    src = src or {}
    rows = []

    def add(layer, provider, dataset, ref, licence):
        rows.append({"Layer": layer, "Provider": provider, "Dataset": dataset, "Reference": ref, "Licence": licence})

    bcn = "Open Data BCN (Ajuntament de Barcelona)"
    if b := src.get("boundaries"):
        add("Barri boundaries", bcn, b.get("resource") or b.get("package", "–"), "–", "CC BY 4.0")
    if p := src.get("population"):
        add("Population (municipal register)", bcn, p.get("resource") or p.get("package", "–"), str(p.get("reference_year") or "–"), "CC BY 4.0")
    if i := src.get("income"):
        add("Household income per capita", bcn, i.get("resource") or i.get("package", "–"), str(i.get("reference_year") or "–"), "CC BY 4.0")
    if src.get("osm_green"):
        add("Parks and gardens", "OpenStreetMap (Overpass API)", "leisure / landuse features", "live query", "ODbL")
    for label, info in (src.get("official_polygons") or {}).items():
        if "error" in info:
            add("Parks > 0.5 ha (city)", bcn, f"{label}: not available", "–", "CC BY 4.0")
        else:
            used = f"{info.get('polygons_kept', '?')} of {info.get('polygons_in_file', '?')} polygons used"
            add("Parks > 0.5 ha (city)", bcn, f"{info.get('resource', label)} ({used})", _year_in(info.get("resource")), "CC BY 4.0")
    if z := src.get("exclusion_zone"):
        names = ", ".join(z.get("features") or []) or "not found"
        add("Excluded natural park", "OpenStreetMap (Overpass API)", names, "live query", "ODbL")
    if src.get("stations"):
        add("Rail and metro stations", "OpenStreetMap (Overpass API)", "railway=station", "live query", "ODbL")
    if rs := src.get("resident_sampling"):
        add("Where residents live", "OpenStreetMap (Overpass API)",
            f"building footprints – {rs.get('points', 0):,} points ({rs.get('method', '?')})", "live query", "ODbL")
    if (r := src.get("register")) and "error" not in r:
        add("Park register (quality check)", bcn, r.get("resource") or r.get("package", "–"), "–", "CC BY 4.0")
    return pd.DataFrame(rows, columns=["Layer", "Provider", "Dataset", "Reference", "Licence"])


def green_layer_summary(gl: dict | None) -> list[tuple[str, str, str]]:
    gl = gl or {}

    def km(key):
        v = gl.get(key)
        return "–" if v is None else f"{v:.2f} km²"

    return [("Green space used", km("final_km2"), "After merging all sources and removing the excluded natural park"),
            ("From OpenStreetMap", km("osm_km2"), "Parks, gardens, playgrounds, grass and recreation areas"),
            ("From city polygons", km("official_km2"), "Official register of public green spaces larger than 0.5 ha"),
            ("Removed (natural park)", km("excluded_km2"), "Area of green polygons that overlap the excluded Collserola natural park")]
