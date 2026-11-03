"""Synthetic data builders shared by the tests (no geo libraries needed)."""
import json

import numpy as np
import pandas as pd

from greenspace.config import CityConfig, from_dict
from greenspace.schema import EXPORT_COLS
from greenspace.scoring import score_frame
from greenspace.stats import city_stats
from greenspace.store import RunStore


def make_cfg(**overrides) -> CityConfig:
    d = {"sources": {"official_polygons": [{"label": "a", "package": "p"}]}}
    d.update(overrides)
    return from_dict(d)


def make_frame(n=73, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    pop = rng.integers(8_000, 60_000, n).astype(float)
    area = rng.uniform(0.3, 6, n) * 1e6
    green = area * rng.uniform(0.0, 0.3, n)
    inc = rng.uniform(12_000, 40_000, n)
    df = pd.DataFrame({
        "barri_code": np.arange(1, n + 1), "barri": [f"Barri {i}" for i in range(1, n + 1)],
        "district": [f"District {i % 10 + 1}" for i in range(n)],
        "population": pop, "area_m2": area, "green_m2": green,
        "green_cover_pct": green / area * 100, "pop_density_km2": pop / (area / 1e6), "green_m2_pp": green / pop,
        "people_per_1000m2_green": pop / (green / 1000), "income_eur_pc": inc,
        "n_stations": rng.integers(0, 5, n),
        "share_300m_05ha": rng.uniform(0.2, 1, n), "share_1km_5ha": rng.uniform(0.1, 1, n),
        "natural_park_share": np.where(np.arange(n) < 5, 0.9, 0.0)})
    w = np.average(inc, weights=pop)
    df["rfd_index"] = inc / w * 100
    df["low_income"] = df["rfd_index"] < 75
    return df


def make_scored(n=73, seed=0, cfg=None) -> pd.DataFrame:
    return score_frame(make_frame(n, seed), cfg or make_cfg())


def square(i, n_cols=10):
    x, y = (i % n_cols) * 0.01, (i // n_cols) * 0.01
    return [[[x, y], [x + 0.01, y], [x + 0.01, y + 0.01], [x, y + 0.01], [x, y]]]


def write_run(data_dir, cfg=None, df=None, slug="barcelona", status="published") -> str:
    """Create a committed run (CSV + GeoJSON + metadata) exactly as the pipeline would."""
    cfg = cfg or make_cfg()
    df = make_scored() if df is None else df
    store = RunStore(data_dir, slug)
    rid, d = store.begin()
    df[EXPORT_COLS].to_csv(d / "barris.csv", index=False)
    feats = [{"type": "Feature", "properties": json.loads(r.to_json()), "geometry": {"type": "Polygon", "coordinates": square(i)}}
             for i, (_, r) in enumerate(df[EXPORT_COLS].iterrows())]
    (d / "barris.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    (d / "green_patches.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    (d / "checks.json").write_text(json.dumps([{"name": "unit_count", "status": "pass", "detail": "ok"}]))
    from greenspace.config import to_dict
    (d / "metadata.json").write_text(json.dumps({
        "run_id": rid, "city": "Barcelona", "status": status, "software_version": "test",
        "finished_utc": "2026-11-01T03:00:00+00:00", "checks_summary": {"pass": 1, "warn": 0, "fail": 0},
        "stats": city_stats(df, cfg), "green_layer": {"final_km2": 1.0}, "sources": {}, "config": to_dict(cfg),
        "attribution": ["x"]}, default=str))
    store.commit(rid)
    return rid
