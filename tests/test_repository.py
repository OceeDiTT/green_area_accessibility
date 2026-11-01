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
