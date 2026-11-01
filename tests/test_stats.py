import pytest
from greenspace.stats import city_stats, district_summary, wmedian
import pandas as pd


def test_city_stats_consistency(scored, cfg):
    s = city_stats(scored, cfg)
    assert s["units"] == 73 and s["population"] == int(scored["population"].sum())
    assert s["green_cover_pct"] == pytest.approx(scored["green_m2"].sum() / scored["area_m2"].sum() * 100)
    assert 0 <= s["pop_share_below_who_target"] <= 1
    assert len(s["equity_by_income_quartile"]) == 4
    assert -1 <= s["spearman_income_vs_green_per_capita"] <= 1


def test_wmedian():
    x, w = pd.Series([1, 2, 3, 4], name="x"), pd.Series([1, 1, 1, 10])
    assert wmedian(x, w) == 4


def test_district_summary(scored):
    d = district_summary(scored)
    assert d["units"].sum() == 73 and d["population"].sum() == int(scored["population"].sum())
    assert d["access_score_pop_weighted"].is_monotonic_decreasing
