"""REST API (read-only). Run:  uvicorn greenspace.api.app:app   |   greenspace serve"""
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__
from .repository import NoRunAvailable, NotFound, Repository, data_age_days

DATA_DIR = os.getenv("GREENSPACE_DATA_DIR", "data")
CITY = os.getenv("GREENSPACE_CITY", "barcelona")
ROOT_PATH = os.getenv("API_ROOT_PATH", "")                       # e.g. /api when served behind a reverse proxy under /api
EXPOSE_GREEN_LAYER = os.getenv("EXPOSE_GREEN_LAYER", "true").lower() != "false"
CORS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

app = FastAPI(
    title="Green Space Accessibility API",
    version=__version__,
    root_path=ROOT_PATH,
    description=("Green Accessibility Score, ranking and equity indicators per barri. "
                 "Data: Ajuntament de Barcelona - Open Data BCN (CC BY 4.0) and (c) OpenStreetMap contributors (ODbL)."))
app.add_middleware(CORSMiddleware, allow_origins=CORS, allow_methods=["GET"], allow_headers=["*"])
repo = Repository(DATA_DIR, CITY)


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    resp = await call_next(request)
    if request.method == "GET" and resp.status_code == 200 and request.url.path.startswith("/v1"):
        resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


def _call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except NoRunAvailable as e:
        raise HTTPException(503, str(e))
    except NotFound as e:
        raise HTTPException(404, str(e.args[0]))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/health", tags=["ops"], summary="Liveness probe")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/ready", tags=["ops"], summary="Readiness probe (a published run exists)")
def ready():
    rid = repo.store.latest_id()
    if rid is None:
        raise HTTPException(503, "no published run yet")
    md = repo.store.metadata(rid) or {}
    return {"status": "ready", "run_id": rid, "data_age_days": data_age_days(md.get("finished_utc"))}


@app.get("/v1/meta", tags=["metadata"], summary="Live run, sources, parameters, attribution")
def meta():
    return _call(repo.meta)


@app.get("/v1/quality", tags=["metadata"], summary="Data-quality checks of the live run")
def quality():
    return _call(repo.checks)


@app.get("/v1/stats", tags=["summary"], summary="City-wide indicators, equity quartiles and green-layer report")
def stats():
    return _call(repo.stats)


@app.get("/v1/barris", tags=["barris"], summary="List / filter / sort barris")
def list_barris(district: str | None = None, tier: str | None = Query(None, description="Very low | Low | Medium | High | Very high"),
                min_score: float | None = None, max_score: float | None = None, low_income: bool | None = None,
                near_natural_park: bool | None = Query(None, description="barris where most residents live next to the excluded natural park"),
                q: str | None = Query(None, description="name contains"),
                sort: str = "access_rank", order: str = "asc",
                limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return _call(repo.list_barris, district, tier, min_score, max_score, low_income, q, sort, order, limit, offset, near_natural_park)


@app.get("/v1/barris/{code}", tags=["barris"], summary="One barri with all metrics and its district peers")
def get_barri(code: int):
    return _call(repo.get_barri, code)


@app.get("/v1/ranking", tags=["ranking"], summary="Top / bottom barris by accessibility score or investment priority")
def ranking(by: str = Query("access", description="access | priority"),
            order: str = Query("best", description="best = rank 1 first (for priority: most urgent), worst = last ranks first"),
            limit: int = Query(10, ge=1, le=100)):
    return _call(repo.ranking, by, order, limit)


@app.get("/v1/districts", tags=["summary"], summary="District summary (population-weighted score)")
def districts():
    return _call(repo.districts)


@app.get("/v1/geojson", tags=["geo"], summary="Barri polygons (WGS84) with metrics as properties")
def geojson(props: str | None = Query(None, description="comma-separated property names to keep")):
    return _call(repo.geojson, [p for p in props.split(",") if p] if props else None)


@app.get("/v1/layers/{name}", tags=["geo"], summary="Context layers: green | stations (GeoJSON, WGS84)")
def layer(name: str):
    if name == "green" and not EXPOSE_GREEN_LAYER:
        raise HTTPException(404, "this layer is not published by this deployment")
    return _call(repo.layer, name)
