import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from helpers import write_run  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GREENSPACE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GREENSPACE_CITY", "barcelona")
    import greenspace.api.app as app_module
    app_module = importlib.reload(app_module)
    return TestClient(app_module.app), tmp_path


def test_health_and_ready_without_data(client):
    c, _ = client
    assert c.get("/health").status_code == 200
    assert c.get("/ready").status_code == 503
    assert c.get("/v1/stats").status_code == 503


def test_endpoints_with_data(client):
    c, tmp = client
    write_run(tmp)
    assert c.get("/ready").status_code == 200
    r = c.get("/v1/barris", params={"limit": 3})
    assert r.status_code == 200 and r.json()["total"] == 73 and len(r.json()["items"]) == 3
    assert r.headers["cache-control"].startswith("public")
    assert c.get("/v1/barris/1").json()["barri_code"] == 1
    assert c.get("/v1/barris/9999").status_code == 404
    assert c.get("/v1/barris", params={"sort": "bogus"}).status_code == 400
    assert c.get("/v1/barris", params={"limit": 9999}).status_code == 422
    assert c.get("/v1/ranking", params={"by": "priority", "limit": 5}).json()[0]["priority_rank"] == 1
    assert c.get("/v1/geojson", params={"props": "access_score"}).json()["features"][0]["properties"]["access_score"] is not None
    assert c.get("/v1/districts").status_code == 200 and c.get("/v1/meta").json()["city"] == "Barcelona"
