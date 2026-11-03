"""Export the live run into a small, public, git-friendly snapshot (used by the free deployment).

published/runs/<city>/<run_id>/{barris.csv, barris.geojson, districts.csv, metadata.json, checks.json}  +  latest.json
Same layout as the run store, so the API data layer and the dashboard read it unchanged. Large / derived layers
(green_patches, stations, GeoPackage) are deliberately NOT published.
"""
import json
import os
import shutil
from pathlib import Path

from .store import RunStore

PUBLIC_FILES = ["barris.csv", "barris.geojson", "districts.csv", "metadata.json", "checks.json"]
MAX_MB = 20


class PublishError(RuntimeError):
    pass


def publish(data_dir, dest_dir, slug: str, keep: int = 1) -> dict:
    src = RunStore(data_dir, slug, create=False)
    rid = src.latest_id()
    if rid is None:
        raise PublishError("No published run to export. Run: greenspace run")
    md = src.metadata(rid) or {}
    if md.get("status") != "published":
        raise PublishError(f"Run {rid} has status '{md.get('status')}' (forced or rejected) - refusing to publish it")
    missing = [f for f in PUBLIC_FILES if f not in ("districts.csv",) and not (src.path(rid) / f).exists()]
    if missing:
        raise PublishError(f"Run {rid} is missing {missing}")

    root = Path(dest_dir) / "runs" / slug
    root.mkdir(parents=True, exist_ok=True)
    tmp, final = root / f"{rid}.tmp", root / rid
    for p in (tmp, final):
        if p.exists():
            shutil.rmtree(p)
    tmp.mkdir()
    total = 0
    for f in PUBLIC_FILES:
        s = src.path(rid) / f
        if s.exists():
            shutil.copy2(s, tmp / f)
            total += s.stat().st_size
    if total > MAX_MB * 1024 * 1024:
        shutil.rmtree(tmp)
        raise PublishError(f"Snapshot is {total / 1e6:.1f} MB (> {MAX_MB} MB); refusing to commit it to git")
    os.replace(tmp, final)
    pointer = root / "latest.json"
    pointer.with_suffix(".part").write_text(json.dumps({"run_id": rid}), encoding="utf-8")
    os.replace(pointer.with_suffix(".part"), pointer)

    removed = []
    old = sorted(p for p in root.iterdir() if p.is_dir() and p.name != rid)
    for p in (old[:-(keep - 1)] if keep > 1 else old):
        shutil.rmtree(p, ignore_errors=True)
        removed.append(p.name)
    return {"run_id": rid, "dest": str(final), "files": sorted(p.name for p in final.iterdir()),
            "megabytes": round(total / 1e6, 2), "removed_old_runs": removed}
