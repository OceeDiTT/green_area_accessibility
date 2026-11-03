"""Data-quality gate. A run is only published when no check has status 'fail'."""
from dataclasses import dataclass, asdict

import pandas as pd

from .config import CityConfig


@dataclass
class Check:
    name: str
    status: str          # pass | warn | fail
    detail: str

    def to_dict(self):
        return asdict(self)


def has_failures(checks) -> bool:
    return any(c.status == "fail" for c in checks)


def summarize(checks) -> dict:
    return {s: sum(c.status == s for c in checks) for s in ("pass", "warn", "fail")}


def run_checks(df: pd.DataFrame, ctx: dict, cfg: CityConfig, previous: pd.DataFrame | None = None) -> list[Check]:
    v = cfg.validation
    out: list[Check] = []

    def add(name, ok, detail, warn_only=False):
        out.append(Check(name, "pass" if ok else ("warn" if warn_only else "fail"), detail))

    n = len(df)
    add("unit_count", n == v.n_units, f"{n} units (expected {v.n_units})")
    add("unique_codes", not df["barri_code"].duplicated().any(), "unit codes are unique")

    pop = df["population"]
    add("population_complete", not pop.isna().any(), f"{int(pop.isna().sum())} units without population")
    lo, hi = v.population_range
    add("population_total", lo <= pop.sum() <= hi, f"total {pop.sum():,.0f} (expected {lo:,.0f}-{hi:,.0f})")

    miss = float(df["income_eur_pc"].isna().mean())
    status = "pass" if miss == 0 else ("warn" if miss <= 0.2 else "fail")
    out.append(Check("income_coverage", status, f"{miss:.0%} of units without income"))

    py, iy = ctx.get("population_year"), ctx.get("income_year")
    if py and iy:
        add("reference_year_gap", abs(py - iy) <= v.max_year_gap,
            f"population {py} vs income {iy} (max gap {v.max_year_gap})", warn_only=True)

    city_cover = float(df["green_m2"].sum() / df["area_m2"].sum() * 100)
    clo, chi = v.city_green_cover_pct_range
    add("city_green_cover", clo <= city_cover <= chi, f"{city_cover:.1f}% (expected {clo}-{chi}%)")
    add("unit_cover_bounds", bool(df["green_cover_pct"].between(0, 100.0001).all()), "per-unit coverage within 0-100%")

    absurd = df[df["green_cover_pct"] > v.reject_unit_cover_pct].sort_values("green_cover_pct", ascending=False)
    add("unit_cover_sane", absurd.empty,
        f"No barri above {v.reject_unit_cover_pct:.0f}% green cover" if absurd.empty else
        f"{len(absurd)} units above {v.reject_unit_cover_pct:.0f}% green cover: "
        + ", ".join(f"{n} ({c:.0f}%)" for n, c in zip(absurd["barri"].head(8), absurd["green_cover_pct"].head(8)))
        + " - a green source almost certainly contains non-green polygons")

    hi = df[df["green_cover_pct"] > v.max_unit_cover_pct].sort_values("green_cover_pct", ascending=False)
    add("unit_cover_plausible", hi.empty,
        f"No barri above {v.max_unit_cover_pct:.0f}% green cover" if hi.empty else
        f"{len(hi)} units above {v.max_unit_cover_pct:.0f}% green cover: "
        + ", ".join(f"{n} ({c:.0f}%)" for n, c in zip(hi["barri"].head(8), hi["green_cover_pct"].head(8)))
        + " - verify (large parks can explain this; otherwise a green source may contain non-green polygons)", warn_only=True)

    s = df["access_score"]
    add("score_valid", bool(s.notna().all() and s.between(0, 100).all()), "scores present and within 0-100")

    rate = ctx.get("register_match_rate")
    if rate is None:
        out.append(Check("register_match", "warn", "city park register could not be read - cross-check skipped"))
    else:
        add("register_match", rate >= v.min_register_match,
            f"{rate:.0%} of registered parks are inside the hybrid green layer (min {v.min_register_match:.0%})",
            warn_only=True)

    zone = bool(ctx.get("exclusion_zone_found"))
    add("exclusion_zone", zone,
        "exclusion zone applied (" + ", ".join(cfg.green.exclusion.name_patterns) + ")" if zone
        else "exclusion zone NOT found - excluded areas may be counted as green",
        warn_only=not cfg.green.exclusion.required)

    if cfg.green.use_official:
        add("official_polygons", float(ctx.get("official_km2", 0)) > 0,
            f"official polygon layers contribute {ctx.get('official_km2', 0):.2f} km²", warn_only=True)

    pm = ctx.get("points_method")
    add("sampling_method", pm in (None, cfg.sampling.method),
        f"residents located with '{pm}' (configured: '{cfg.sampling.method}')", warn_only=True)

    npts = int(ctx.get("n_points", 0))
    add("sample_points", npts >= v.min_sample_points,
        f"{npts:,} resident sample points ({ctx.get('points_method', '?')})", warn_only=True)
    no_pts = list(ctx.get("units_without_points") or [])
    add("units_with_points", not no_pts,
        f"{len(no_pts)} units without any resident sample point (their proximity shares are 0): {', '.join(no_pts[:8])}",
        warn_only=True)
    filled = list(ctx.get("units_grid_filled") or [])
    add("units_grid_filled", not filled,
        f"{len(filled)} units had no building footprints; residents sampled on a grid there: {', '.join(filled[:8])}",
        warn_only=True)

    if previous is not None and {"barri_code", "access_rank"} <= set(previous.columns):
        m = df[["barri_code", "access_rank"]].merge(previous[["barri_code", "access_rank"]], on="barri_code",
                                                    suffixes=("", "_prev"))
        if len(m):
            shift = (m["access_rank"] - m["access_rank_prev"]).abs()
            add("rank_drift", shift.mean() <= v.max_mean_rank_shift,
                f"mean rank shift vs previous run {shift.mean():.1f} (max {shift.max():.0f}); limit {v.max_mean_rank_shift}",
                warn_only=True)
    return out
