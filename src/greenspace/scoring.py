"""Green Accessibility Score, ranking, priority index and rank stability (pure pandas/numpy)."""
import numpy as np
import pandas as pd

from .config import CityConfig
from .schema import TIERS


def winsor_minmax(s, lo=0.05, hi=0.95) -> pd.Series:
    s = pd.Series(s, dtype=float)
    a, c = s.quantile(lo), s.quantile(hi)
    return ((s.clip(a, c) - a) / (c - a) * 100) if c > a else s * 0


def components(df: pd.DataFrame, lo=0.05, hi=0.95) -> pd.DataFrame:
    return pd.DataFrame({
        "c_percapita": winsor_minmax(df["green_m2_pp"], lo, hi),
        "c_prox300":   df["share_300m_05ha"] * 100,
        "c_large1km":  df["share_1km_5ha"] * 100,
        "c_coverage":  winsor_minmax(df["green_cover_pct"], lo, hi),
    }, index=df.index)


def accessibility_score(comp: pd.DataFrame, weights: dict) -> pd.Series:
    w = pd.Series(weights, dtype=float)
    w = w / w.sum()
    return (comp[w.index] * w).sum(axis=1)


def priority_index(df: pd.DataFrame, score: pd.Series, pw: dict) -> pd.Series:
    need = 100 - score
    dens = df["pop_density_km2"].rank(pct=True) * 100
    inc = (1 - df["rfd_index"].rank(pct=True)) * 100
    w = pd.Series(pw, dtype=float)
    w = w / w.sum()
    return w["access_need"] * need + w["density"] * dens + w["income_need"] * inc.fillna(inc.median())


def rank_stability(comp: pd.DataFrame, base_w: dict, n=2000, concentration=50, seed=42) -> pd.DataFrame:
    """Ranks under n random weightings drawn (Dirichlet) around the base weights."""
    rng = np.random.default_rng(seed)
    keys = list(base_w)
    alpha = np.array([base_w[k] for k in keys], float)
    alpha = alpha / alpha.sum() * concentration
    W = rng.dirichlet(alpha, size=n)
    scores = comp[keys].values @ W.T                      # (units, n)
    ranks = (-scores).argsort(axis=0).argsort(axis=0) + 1
    return pd.DataFrame({"rank_p05": np.percentile(ranks, 5, axis=1),
                         "rank_median": np.median(ranks, axis=1),
                         "rank_p95": np.percentile(ranks, 95, axis=1)}, index=comp.index)


def score_frame(df: pd.DataFrame, cfg: CityConfig) -> pd.DataFrame:
    """Return df with component scores, score, rank, tier, priority and rank-stability columns added."""
    s = cfg.scoring
    out = df.drop(columns=[c for c in df.columns if c.startswith("c_")], errors="ignore").copy()
    comp = components(out, s.winsor_lo, s.winsor_hi)
    out = out.join(comp)
    out["access_score"] = accessibility_score(comp, s.weights)
    out["access_rank"] = out["access_score"].rank(ascending=False, method="min").astype(int)
    out["access_tier"] = pd.qcut(out["access_score"].rank(method="first"), 5, labels=TIERS).astype(str)
    out["priority_index"] = priority_index(out, out["access_score"], s.priority_weights)
    out["priority_rank"] = out["priority_index"].rank(ascending=False, method="min").astype(int)
    out["meets_who_target"] = out["green_m2_pp"] >= cfg.standards.who_target_m2_pp
    # context only: does NOT enter the score. Residents next to an excluded natural park have a better real situation than the score shows.
    share = out["natural_park_share"] if "natural_park_share" in out else pd.Series(0.0, index=out.index)
    out["near_natural_park"] = share >= cfg.green.exclusion.flag_share
    stab = rank_stability(comp, s.weights, s.stability_draws, s.stability_concentration, s.seed)
    out = out.join(stab)
    out["rank_range90"] = out["rank_p95"] - out["rank_p05"]
    return out
