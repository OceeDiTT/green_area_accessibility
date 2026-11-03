"""One `get(path, **params)` for the dashboard, backed either by the REST API (API_URL) or by published files (no server)."""
from ..api.repository import NoRunAvailable, NotFound, Repository


def route(repo: Repository, path: str, params: dict):
    """Map an API path to the repository call that serves it (same shapes as the REST API)."""
    p = path.rstrip("/")
    if p == "/v1/meta":
        return repo.meta()
    if p == "/v1/stats":
        return repo.stats()
    if p == "/v1/quality":
        return repo.checks()
    if p == "/v1/districts":
        return repo.districts()
    if p == "/v1/geojson":
        props = params.get("props")
        return repo.geojson([x for x in props.split(",") if x] if props else None)
    if p == "/v1/barris":
        return repo.list_barris(limit=params.get("limit", 100), sort=params.get("sort", "access_rank"),
                                order=params.get("order", "asc"), offset=params.get("offset", 0))
    if p.startswith("/v1/barris/"):
        return repo.get_barri(int(p.rsplit("/", 1)[1]))
    if p == "/v1/ranking":
        return repo.ranking(params.get("by", "access"), params.get("order", "best"), params.get("limit", 10))
    raise KeyError(f"unsupported path {path}")


def make_getter(api_url: str | None, published_dir, slug: str = "barcelona"):
    """api_url set -> HTTP client; otherwise read the snapshot in `published_dir` directly."""
    if api_url:
        import requests

        def get_http(path: str, **params):
            r = requests.get(f"{api_url.rstrip('/')}{path}", params=params, timeout=60)
            if r.status_code == 503:
                return {"_unavailable": r.json().get("detail", "no data")}
            r.raise_for_status()
            return r.json()
        return get_http

    repo = Repository(published_dir, slug)

    def get_files(path: str, **params):
        try:
            return route(repo, path, params)
        except NoRunAvailable as e:
            return {"_unavailable": str(e)}
        except NotFound as e:
            raise KeyError(str(e.args[0])) from e
    return get_files
