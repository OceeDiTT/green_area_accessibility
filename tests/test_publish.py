import json

import pytest
from greenspace.api.repository import Repository
from greenspace.dashboard.data_access import make_getter, route
from greenspace.publish import PUBLIC_FILES, PublishError, publish
from helpers import make_scored, write_run


def test_publish_creates_a_snapshot_the_dashboard_can_read(tmp_path):
    src, dest = tmp_path / "data", tmp_path / "published"
    rid = write_run(src)
    res = publish(src, dest, "barcelona")
    assert res["run_id"] == rid and set(res["files"]) <= set(PUBLIC_FILES) and "barris.geojson" in res["files"]
    run = dest / "runs" / "barcelona" / rid
    assert not (run / "green_patches.geojson").exists()                      # derived layers are not published
    assert json.loads((dest / "runs" / "barcelona" / "latest.json").read_text())["run_id"] == rid
    repo = Repository(dest, "barcelona")
    assert repo.meta()["run_id"] == rid and repo.stats()["units"] == 73 and len(repo.geojson()["features"]) == 73


def test_publish_keeps_only_the_newest_run(tmp_path):
    import time
    src, dest = tmp_path / "data", tmp_path / "published"
    first = write_run(src)
    publish(src, dest, "barcelona")
    time.sleep(1.1)
    second = write_run(src, df=make_scored(seed=9))
    res = publish(src, dest, "barcelona")
    assert res["removed_old_runs"] == [first]
    assert sorted(p.name for p in (dest / "runs" / "barcelona").iterdir() if p.is_dir()) == [second]
    assert Repository(dest, "barcelona").meta()["run_id"] == second


def test_publish_refuses_without_a_run_or_with_a_forced_run(tmp_path):
    with pytest.raises(PublishError):
        publish(tmp_path / "empty", tmp_path / "published", "barcelona")
    write_run(tmp_path / "data", status="rejected")
    with pytest.raises(PublishError):
        publish(tmp_path / "data", tmp_path / "published", "barcelona")


def test_file_getter_serves_the_same_shapes_as_the_api(tmp_path):
    write_run(tmp_path)
    get = make_getter(None, tmp_path)
    assert get("/v1/meta")["city"] == "Barcelona" and get("/v1/stats")["units"] == 73
    assert len(get("/v1/barris", limit=500, sort="access_rank")["items"]) == 73
    assert get("/v1/barris/5")["barri_code"] == 5 and get("/v1/ranking", by="priority", order="best", limit=3)[0]["priority_rank"] == 1
    assert len(get("/v1/geojson")["features"]) == 73 and get("/v1/quality")[0]["name"] == "unit_count"
    assert len(get("/v1/districts")) == 10
    with pytest.raises(KeyError):
        get("/v1/barris/9999")
    with pytest.raises(KeyError):
        route(Repository(tmp_path, "barcelona"), "/v1/unknown", {})


def test_file_getter_reports_missing_data_instead_of_crashing(tmp_path):
    assert "_unavailable" in make_getter(None, tmp_path / "nothing")("/v1/meta")
