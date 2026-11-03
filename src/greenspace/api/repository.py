"""Read-side data access for the API. Pure pandas/json (no geo libraries), so the API image stays small."""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..schema import EXPORT_COLS, MAP_METRICS, TIERS
from ..stats import district_summary
from ..store import RunStore

SORTABLE = set(MAP_METRICS) | {"barri", "district", "barri_code"}


def data_age_days(finished_utc, now=None):
    """Age of the live data in days (for freshness monitoring); None if unknown."""
    try:
        d = datetime.fromisoformat(str(finished_utc))
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return round(max(0.0, ((now or datetime.now(timezone.utc)) - d).total_seconds() / 86400), 1)


class NoRunAvailable(RuntimeError):
    pass


class NotFound(KeyError):
    pass


@dataclass
class RunData:
    run_id: str
    df: pd.DataFrame
    metadata: dict
    checks: list
    districts: pd.DataFrame


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe records (NaN -> null, numpy scalars -> python)."""
    return json.loads(df.to_json(orient="records"))


class Repository:
    def __init__(self, data_dir, slug: str):
        self.store = RunStore(data_dir, slug, create=False)
        self._cache: RunData | None = None
        self._files: dict = {}

    # -- loading (re-reads only when the live run changes) -------------------------------------------------
    def load(self) -> RunData:
        rid = self.store.latest_id()
        if rid is None:
            raise NoRunAvailable("No published run yet. Run the pipeline first (greenspace run).")
        if self._cache is None or self._cache.run_id != rid:
            df = self.store.load_table(rid)
            if df is None:
                raise NoRunAvailable(f"Run {rid} has no barris.csv")
            for col, default in (("natural_park_share", np.nan), ("near_natural_park", False)):   # runs made before these columns existed
                if col not in df.columns:
                    df[col] = default
            df["low_income"] = df["low_income"].astype(bool)
            df["near_natural_park"] = df["near_natural_park"].fillna(False).astype(bool)
            df["meets_who_target"] = df["meets_who_target"].astype(bool)
            checks_p = self.store.path(rid) / "checks.json"
            self._cache = RunData(rid, df, self.store.metadata(rid) or {},
                                  json.loads(checks_p.read_text(encoding="utf-8")) if checks_p.exists() else [],
                                  district_summary(df))
            self._files = {}
        return self._cache

    def _file_json(self, name: str):
        d = self.load()
        if name not in self._files:
            p: Path = self.store.path(d.run_id) / name
            self._files[name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        return self._files[name]

    # -- queries --------------------------------------------------------------------------------------------
    def meta(self) -> dict:
        d = self.load()
        m = d.metadata
        cfg = m.get("config", {})
        return {"run_id": d.run_id, "city": m.get("city"), "status": m.get("status"),
                "started_utc": m.get("started_utc"), "finished_utc": m.get("finished_utc"), "duration_s": m.get("duration_s"),
                "data_age_days": data_age_days(m.get("finished_utc")),
                "software_version": m.get("software_version"),
                "checks_summary": m.get("checks_summary"), "attribution": m.get("attribution"),
                "sources": m.get("sources"),
                "parameters": {"weights": cfg.get("scoring", {}).get("weights"),
                               "priority_weights": cfg.get("scoring", {}).get("priority_weights"),
                               "standards": cfg.get("standards"), "sampling": cfg.get("sampling"),
                               "low_income_index": cfg.get("equity", {}).get("low_income_index")}}

    def stats(self) -> dict:
        d = self.load()
        return {**d.metadata.get("stats", {}), "green_layer": d.metadata.get("green_layer", {})}

    def checks(self) -> list:
        return self.load().checks

    def list_barris(self, district=None, tier=None, min_score=None, max_score=None, low_income=None, q=None,
                    sort="access_rank", order="asc", limit=100, offset=0, near_natural_park=None) -> dict:
        df = self.load().df
        if sort not in SORTABLE:
            raise ValueError(f"sort must be one of {sorted(SORTABLE)}")
        if order not in ("asc", "desc"):
            raise ValueError("order must be 'asc' or 'desc'")
        if tier is not None and tier not in TIERS:
            raise ValueError(f"tier must be one of {TIERS}")
        if district:
            df = df[df["district"].str.casefold() == district.casefold()]
        if tier:
            df = df[df["access_tier"] == tier]
        if min_score is not None:
            df = df[df["access_score"] >= min_score]
        if max_score is not None:
            df = df[df["access_score"] <= max_score]
        if low_income is not None:
            df = df[df["low_income"] == low_income]
        if near_natural_park is not None:
            df = df[df["near_natural_park"] == near_natural_park]
        if q:
            df = df[df["barri"].str.casefold().str.contains(q.casefold(), regex=False)]
        df = df.sort_values(sort, ascending=(order == "asc"), kind="stable")
        total = len(df)
        limit = max(1, min(int(limit), 500))
        page = df.iloc[max(int(offset), 0): max(int(offset), 0) + limit]
        return {"total": total, "limit": limit, "offset": max(int(offset), 0), "items": _records(page[EXPORT_COLS])}

    def get_barri(self, code: int) -> dict:
        df = self.load().df
        row = df[df["barri_code"] == code]
        if row.empty:
            raise NotFound(f"No barri with code {code}")
        rec = _records(row[EXPORT_COLS])[0]
        rec["same_district_ranking"] = _records(
            df[df["district"] == row["district"].iloc[0]].sort_values("access_rank")[["barri_code", "barri", "access_score", "access_rank"]])
        return rec

    def ranking(self, by="access", order="best", limit=10) -> list[dict]:
        if by not in ("access", "priority"):
            raise ValueError("by must be 'access' or 'priority'")
        if order not in ("best", "worst"):
            raise ValueError("order must be 'best' or 'worst'")
        df = self.load().df
        rank_col = "access_rank" if by == "access" else "priority_rank"
        val_col = "access_score" if by == "access" else "priority_index"
        ascending = order == "best"          # rank 1 first; for 'priority' rank 1 = the most urgent barri
        cols = ["barri_code", "barri", "district", rank_col, val_col, "access_score", "population", "green_m2_pp",
                "share_300m_05ha", "rfd_index"]
        cols = list(dict.fromkeys(cols))
        out = df.sort_values(rank_col, ascending=ascending).head(max(1, min(int(limit), 100)))
        return _records(out[cols])

    def districts(self) -> list[dict]:
        return _records(self.load().districts)

    def geojson(self, props: list[str] | None = None) -> dict:
        gj = self._file_json("barris.geojson")
        if gj is None:
            raise NoRunAvailable("barris.geojson missing in the live run")
        if not props:
            return gj
        unknown = set(props) - set(EXPORT_COLS)
        if unknown:
            raise ValueError(f"unknown properties {sorted(unknown)}")
        keep = set(props) | {"barri_code", "barri"}
        return {**gj, "features": [{**f, "properties": {k: v for k, v in f["properties"].items() if k in keep}}
                                   for f in gj["features"]]}

    def layer(self, name: str) -> dict:
        files = {"green": "green_patches.geojson", "stations": "stations.geojson"}
        if name not in files:
            raise ValueError(f"layer must be one of {sorted(files)}")
        gj = self._file_json(files[name])
        if gj is None:
            raise NotFound(f"layer '{name}' not available in the live run")
        return gj
