"""Minimal CKAN client (Open Data BCN and any other CKAN portal)."""
import io
import logging
from pathlib import Path

import pandas as pd

from .http import download_bytes, make_session
from .tabular import pick_resource

log = logging.getLogger(__name__)


class CkanClient:
    def __init__(self, base: str, session=None):
        self.base = base.rstrip("/")
        self.session = session or make_session()

    def call(self, action: str, **params):
        r = self.session.get(f"{self.base}/{action}", params=params, timeout=90)
        r.raise_for_status()
        j = r.json()
        if not j.get("success"):
            raise RuntimeError(f"CKAN {action} failed: {j}")
        return j["result"]

    def search_packages(self, q: str, rows: int = 10) -> pd.DataFrame:
        res = self.call("package_search", q=q, rows=rows)
        return pd.DataFrame([{"name": p["name"], "title": p["title"], "n_resources": len(p["resources"])}
                             for p in res["results"]], columns=["name", "title", "n_resources"])

    def list_resources(self, package_id: str) -> pd.DataFrame:
        pkg = self.call("package_show", id=package_id)
        rows = []
        for r in pkg["resources"]:
            url = r.get("url") or ""
            fmt = (r.get("format") or Path(url.split("?")[0]).suffix.lstrip(".")).lower()
            rows.append({"id": r["id"], "name": r.get("name") or "", "format": fmt, "url": url,
                         "datastore_active": bool(r.get("datastore_active"))})
        return pd.DataFrame(rows, columns=["id", "name", "format", "url", "datastore_active"])

    def resolve_package(self, candidates, search_query: str) -> str:
        for c in candidates:
            try:
                self.call("package_show", id=c)
                return c
            except Exception:
                continue
        hits = self.search_packages(search_query)
        if hits.empty:
            raise RuntimeError(f"No CKAN package found for {list(candidates)} / '{search_query}'")
        log.warning("Packages %s not found - using best search hit '%s'. VERIFY.", list(candidates), hits.iloc[0]["name"])
        return hits.iloc[0]["name"]

    def datastore_all(self, resource_id: str, page: int = 10_000) -> pd.DataFrame:
        out, offset = [], 0
        while True:
            res = self.call("datastore_search", resource_id=resource_id, limit=page, offset=offset)
            out += res["records"]
            if len(res["records"]) < page:
                break
            offset += page
        return pd.DataFrame(out).drop(columns=["_id", "_full_text"], errors="ignore")

    def read_table(self, row) -> pd.DataFrame:
        if row["datastore_active"]:
            return self.datastore_all(row["id"])
        raw = download_bytes(row["url"], self.session)
        for enc in ("utf-8-sig", "latin-1"):
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Could not decode CSV from {row['url']}")

    def pick(self, package_id: str, formats=("csv",), target_year=None, name_contains=None):
        return pick_resource(self.list_resources(package_id), formats, target_year, name_contains)
