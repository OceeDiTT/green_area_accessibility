import numpy as np
from greenspace.scoring import accessibility_score, components, priority_index, rank_stability, winsor_minmax
from greenspace.schema import EXPORT_COLS, TIERS
from helpers import make_frame


def test_winsor_bounds():
    s = winsor_minmax(np.arange(100.0))
    assert s.min() == 0 and s.max() == 100
    assert (winsor_minmax([5, 5, 5]) == 0).all()          # constant input must not divide by zero


def test_score_in_range_and_complete(scored, cfg):
    assert scored["access_score"].between(0, 100).all() and scored["access_score"].notna().all()
    assert set(EXPORT_COLS) <= set(scored.columns)
    assert sorted(scored["access_rank"]) == list(range(1, len(scored) + 1))
    assert set(scored["access_tier"]) == set(TIERS)
    assert scored["access_tier"].value_counts().min() >= 14          # five roughly equal tiers


def test_weights_are_normalised(cfg):
    df = make_frame()
    comp = components(df)
    w = cfg.scoring.weights
    assert np.allclose(accessibility_score(comp, w), accessibility_score(comp, {k: v * 7 for k, v in w.items()}))


def test_more_access_never_lowers_score(cfg):
    df = make_frame()
    base = accessibility_score(components(df), cfg.scoring.weights)
    df2 = df.copy()
    df2.loc[0, "share_300m_05ha"] = 1.0
    assert accessibility_score(components(df2), cfg.scoring.weights)[0] >= base[0]


def test_priority_prefers_dense_poor_low_access(cfg):
    df = make_frame(n=40)
    df.loc[0, ["pop_density_km2", "rfd_index"]] = [df["pop_density_km2"].max() * 2, df["rfd_index"].min() / 2]
    score = accessibility_score(components(df), cfg.scoring.weights)
    score[0] = 0
    pi = priority_index(df, score, cfg.scoring.priority_weights)
    assert pi.idxmax() == 0 and pi.between(0, 100).all()


def test_priority_handles_missing_income(cfg):
    df = make_frame(n=30)
    df.loc[3, "rfd_index"] = np.nan
    pi = priority_index(df, accessibility_score(components(df), cfg.scoring.weights), cfg.scoring.priority_weights)
    assert pi.notna().all()


def test_rank_stability_is_ordered_and_reproducible(cfg):
    comp = components(make_frame())
    a = rank_stability(comp, cfg.scoring.weights, n=300, seed=1)
    b = rank_stability(comp, cfg.scoring.weights, n=300, seed=1)
    assert a.equals(b)
    assert (a.rank_p05 <= a.rank_median).all() and (a.rank_median <= a.rank_p95).all() and a.rank_p95.max() <= len(comp)


def test_base_rank_sits_inside_stability_band(scored):
    inside = (scored["access_rank"] >= scored["rank_p05"] - 3) & (scored["access_rank"] <= scored["rank_p95"] + 3)
    assert inside.mean() > 0.95
