"""City-level statistics and summaries from a scored unit table (pure pandas)."""
import numpy as np
import pandas as pd

from .config import CityConfig


def _spearman(a: pd.Series, b: pd.Series):
    d = pd.concat([a, b], axis=1).dropna()
    if len(d) < 3:
        return None
    r = d.iloc[:, 0].rank().corr(d.iloc[:, 1].rank())
    return None if pd.isna(r) else float(r)


def wmedian(x: pd.Series, w: pd.Series) -> float:
    d = pd.concat([x, w], axis=1).dropna().sort_values(x.name)
    cw = d.iloc[:, 1].cumsum()
    return float(d.iloc[:, 0][cw >= 0.5 * cw.iloc[-1]].iloc[0])


def city_stats(df: pd.DataFrame, cfg: CityConfig) -> dict:
    pop = df["population"]
    who = cfg.standards.who_target_m2_pp
    below = df[df["green_m2_pp"] < who]
    no_access = ((1 - df["share_300m_05ha"]) * pop)
    quart = []
    inc = df.dropna(subset=["rfd_index"]).copy()
    if len(inc) >= 8:
        inc["q"] = pd.qcut(inc["rfd_index"].rank(method="first"), 4, labels=["Q1 (lowest income)", "Q2", "Q3", "Q4 (highest income)"])
        for q, d in inc.groupby("q", observed=True):
            quart.append({"quartile": str(q), "units": int(len(d)), "population": int(d["population"].sum()),
                          "median_green_m2_pp": wmedian(d["green_m2_pp"], d["population"]),
                          "mean_green_cover_pct": float(d["green_cover_pct"].mean()),
                          "mean_access_score": float(np.average(d["access_score"], weights=d["population"]))})
    return {
        "units": int(len(df)),
        "population": int(pop.sum()),
        "area_km2": float(df["area_m2"].sum() / 1e6),
        "green_km2": float(df["green_m2"].sum() / 1e6),
        "green_cover_pct": float(df["green_m2"].sum() / df["area_m2"].sum() * 100),
        "green_m2_per_capita_city": float(df["green_m2"].sum() / pop.sum()),
        "who_target_m2_pp": who,
        "units_below_who_target": int(len(below)),
        "pop_share_below_who_target": float(below["population"].sum() / pop.sum()),
        "pop_weighted_share_300m_05ha": float(np.average(df["share_300m_05ha"], weights=pop)),
        "estimated_residents_without_300m_access": int(round(no_access.sum())),
        "mean_access_score_pop_weighted": float(np.average(df["access_score"], weights=pop)),
        "low_income_units": int(df["low_income"].sum()),
        "units_near_natural_park": int(df["near_natural_park"].sum()) if "near_natural_park" in df else 0,
        "population_near_natural_park": int(df.loc[df["near_natural_park"], "population"].sum()) if "near_natural_park" in df else 0,
        "spearman_income_vs_green_per_capita": _spearman(df["rfd_index"], df["green_m2_pp"]),
        "spearman_income_vs_access_score": _spearman(df["rfd_index"], df["access_score"]),
        "median_rank_range90": float(df["rank_range90"].median()),
        "equity_by_income_quartile": quart,
    }


def district_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dist, d in df.groupby("district"):
        rows.append({"district": dist, "units": int(len(d)), "population": int(d["population"].sum()),
                     "access_score_pop_weighted": float(np.average(d["access_score"], weights=d["population"])),
                     "green_m2_per_capita": float(d["green_m2"].sum() / d["population"].sum()),
                     "green_cover_pct": float(d["green_m2"].sum() / d["area_m2"].sum() * 100),
                     "mean_priority_index": float(d["priority_index"].mean())})
    return pd.DataFrame(rows).sort_values("access_score_pop_weighted", ascending=False).reset_index(drop=True)
