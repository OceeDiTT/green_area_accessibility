import pytest
from greenspace.api.repository import NoRunAvailable, NotFound, Repository
from helpers import write_run


def test_no_run_raises(tmp_path):
    with pytest.raises(NoRunAvailable):
        Repository(tmp_path, "barcelona").meta()


@pytest.fixture
def repo(tmp_path):
    write_run(tmp_path)
    return Repository(tmp_path, "barcelona")


def test_meta_and_stats(repo):
    m = repo.meta()
    assert m["city"] == "Barcelona" and m["parameters"]["weights"]["c_prox300"] == 0.35
    assert repo.stats()["units"] == 73 and repo.checks()[0]["name"] == "unit_count"


def test_list_filter_sort_page(repo):
    r = repo.list_barris(limit=5)
    assert r["total"] == 73 and len(r["items"]) == 5 and r["items"][0]["access_rank"] == 1
    r = repo.list_barris(district="district 1", limit=500)
    assert r["total"] > 0 and all(i["district"] == "District 1" for i in r["items"])
    r = repo.list_barris(min_score=60, sort="access_score", order="desc", limit=500)
    scores = [i["access_score"] for i in r["items"]]
    assert scores == sorted(scores, reverse=True) and all(s >= 60 for s in scores)
    assert repo.list_barris(q="barri 7", limit=500)["total"] >= 1
    assert repo.list_barris(limit=10, offset=70)["items"].__len__() == 3
    assert repo.list_barris(low_income=True, limit=500)["total"] == int(repo.load().df["low_income"].sum())


def test_invalid_arguments(repo):
    with pytest.raises(ValueError):
        repo.list_barris(sort="drop table")
    with pytest.raises(ValueError):
        repo.list_barris(tier="Great")
    with pytest.raises(ValueError):
        repo.ranking(by="nonsense")


def test_json_safe_records(repo):
    import json
    json.dumps(repo.list_barris(limit=500))             # must not raise (no NaN / numpy types)
    json.dumps(repo.get_barri(1))


def test_get_barri(repo):
    b = repo.get_barri(5)
    assert b["barri_code"] == 5 and len(b["same_district_ranking"]) >= 1
    with pytest.raises(NotFound):
        repo.get_barri(9999)


def test_ranking_access_and_priority(repo):
    best = repo.ranking("access", "best", 3)
    worst = repo.ranking("access", "worst", 3)
    assert best[0]["access_rank"] == 1 and worst[0]["access_rank"] == 73
    pr = repo.ranking("priority", "best", 3)
    assert pr[0]["priority_rank"] == 1


def test_geojson_and_layers(repo):
    gj = repo.geojson()
    assert len(gj["features"]) == 73
    slim = repo.geojson(["access_score"])
    assert set(slim["features"][0]["properties"]) == {"access_score", "barri_code", "barri"}
    with pytest.raises(ValueError):
        repo.geojson(["bogus"])
    assert repo.layer("green")["features"] == []
    with pytest.raises(NotFound):
        repo.layer("stations")


def test_picks_up_a_new_run_without_restart(tmp_path):
    from helpers import make_scored
    repo = Repository(tmp_path, "barcelona")
    first = write_run(tmp_path)
    assert repo.meta()["run_id"] == first
    import time
    time.sleep(1.1)                                           # run ids have 1-second resolution
    second = write_run(tmp_path, df=make_scored(seed=5))
    assert repo.meta()["run_id"] == second != first


def test_natural_park_filter_and_old_runs_without_the_columns(tmp_path):
    from greenspace.schema import EXPORT_COLS
    from helpers import make_scored
    repo = Repository(tmp_path, "barcelona")
    write_run(tmp_path)
    r = repo.list_barris(near_natural_park=True, limit=500)
    assert r["total"] == 5 and all(i["near_natural_park"] for i in r["items"])
    assert repo.list_barris(near_natural_park=False, limit=500)["total"] == 68
    # a run published before the columns existed must still load
    import time, pandas as pd
    time.sleep(1.1)
    rid = write_run(tmp_path, df=make_scored(seed=3))
    p = tmp_path / "runs" / "barcelona" / rid / "barris.csv"
    pd.read_csv(p).drop(columns=["natural_park_share", "near_natural_park"]).to_csv(p, index=False)
    assert repo.list_barris(limit=3)["items"][0]["near_natural_park"] is False
    assert set(EXPORT_COLS) <= set(repo.list_barris(limit=1)["items"][0])


def test_data_age_days():
    from datetime import datetime, timezone
    from greenspace.api.repository import data_age_days
    now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    assert data_age_days("2026-11-01T12:00:00+00:00", now) == 10.0
    assert data_age_days("2026-11-01T12:00:00", now) == 10.0            # naive timestamps are UTC
    assert data_age_days("2027-01-01T00:00:00+00:00", now) == 0.0        # clock skew never gives negative ages
    assert data_age_days(None, now) is None and data_age_days("junk", now) is None


def test_meta_reports_data_age(repo):
    assert repo.meta()["data_age_days"] >= 0
