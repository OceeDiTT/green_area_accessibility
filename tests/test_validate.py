from greenspace.validate import has_failures, run_checks, summarize
from helpers import make_cfg, make_scored


def _ctx(**kw):
    base = dict(population_year=2024, income_year=2023, register_match_rate=0.95, exclusion_zone_found=True,
                official_km2=5.0, n_points=100_000, points_method="buildings", units_without_points=[], units_grid_filled=[])
    base.update(kw)
    return base


def _status(checks, name):
    return next(c.status for c in checks if c.name == name)


def _fit_population(df, cfg):
    lo, hi = cfg.validation.population_range
    df = df.copy()
    df["population"] *= (lo + hi) / 2 / df["population"].sum()
    return df


def test_healthy_run_has_no_failures():
    cfg = make_cfg()
    df = make_scored(cfg=cfg)
    df = _fit_population(df, cfg)
    df["green_m2"] = df["area_m2"] * 0.1
    checks = run_checks(df, _ctx(), cfg)
    assert not has_failures(checks), [c for c in checks if c.status == "fail"]
    assert summarize(checks)["fail"] == 0


def test_missing_exclusion_zone_fails_when_required():
    cfg = make_cfg()
    df = _fit_population(make_scored(cfg=cfg), cfg)
    df["green_m2"] = df["area_m2"] * 0.1
    assert _status(run_checks(df, _ctx(exclusion_zone_found=False), cfg), "exclusion_zone") == "fail"
    cfg2 = make_cfg(green={"exclusion": {"required": False}})
    assert _status(run_checks(df, _ctx(exclusion_zone_found=False), cfg2), "exclusion_zone") == "warn"


def test_wrong_unit_count_and_population_fail():
    cfg = make_cfg()
    df = make_scored(n=60, cfg=cfg)
    st = {c.name: c.status for c in run_checks(df, _ctx(), cfg)}
    assert st["unit_count"] == "fail"


def test_stale_population_year_warns_only():
    cfg = make_cfg()
    df = _fit_population(make_scored(cfg=cfg), cfg)
    df["green_m2"] = df["area_m2"] * 0.1
    assert _status(run_checks(df, _ctx(population_year=2012), cfg), "reference_year_gap") == "warn"


def test_register_mismatch_warns_and_unavailable_warns():
    cfg = make_cfg()
    df = _fit_population(make_scored(cfg=cfg), cfg)
    df["green_m2"] = df["area_m2"] * 0.1
    assert _status(run_checks(df, _ctx(register_match_rate=0.4), cfg), "register_match") == "warn"
    assert _status(run_checks(df, _ctx(register_match_rate=None), cfg), "register_match") == "warn"


def test_rank_drift_detected():
    cfg = make_cfg()
    df = _fit_population(make_scored(cfg=cfg), cfg)
    df["green_m2"] = df["area_m2"] * 0.1
    prev = df[["barri_code", "access_rank"]].copy()
    prev["access_rank"] = len(prev) + 1 - prev["access_rank"]          # completely reversed ranking
    assert _status(run_checks(df, _ctx(), cfg, previous=prev), "rank_drift") == "warn"
    assert _status(run_checks(df, _ctx(), cfg, previous=df[["barri_code", "access_rank"]]), "rank_drift") == "pass"


def test_grid_fallback_is_flagged():
    cfg = make_cfg()
    df = _fit_population(make_scored(cfg=cfg), cfg)
    df["green_m2"] = df["area_m2"] * 0.1
    assert _status(run_checks(df, _ctx(points_method="grid"), cfg), "sampling_method") == "warn"
    assert _status(run_checks(df, _ctx(points_method="buildings"), cfg), "sampling_method") == "pass"


def test_units_without_points_are_named():
    cfg = make_cfg()
    df = _fit_population(make_scored(cfg=cfg), cfg)
    df["green_m2"] = df["area_m2"] * 0.1
    checks = run_checks(df, _ctx(units_without_points=["Montjuïc"], units_grid_filled=["la Marina del Prat Vermell"]), cfg)
    detail = {c.name: c for c in checks}
    assert detail["units_with_points"].status == "warn" and "Montjuïc" in detail["units_with_points"].detail
    assert detail["units_grid_filled"].status == "warn" and "Marina" in detail["units_grid_filled"].detail


def test_implausible_unit_cover_is_flagged_by_name():
    cfg = make_cfg()
    df = _fit_population(make_scored(cfg=cfg), cfg)
    df["green_m2"] = df["area_m2"] * 0.1
    df["green_cover_pct"] = 10.0
    df.loc[0, "green_cover_pct"] = 99.6
    df.loc[0, "barri"] = "el Barri Gòtic"
    c = {x.name: x for x in run_checks(df, _ctx(), cfg)}["unit_cover_plausible"]
    assert c.status == "warn" and "el Barri Gòtic (100%)" in c.detail
