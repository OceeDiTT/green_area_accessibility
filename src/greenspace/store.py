"""Versioned run storage on a plain filesystem (a volume in Docker).

data/runs/<city>/<run_id>/...   committed runs     data/runs/<city>/latest.json   pointer to the live run
Runs are written to <run_id>.tmp and renamed only after validation passes, so readers never see a half-written run.
"""
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class RunStore:
    def __init__(self, data_dir, slug: str, create: bool = True):
        self.root = Path(data_dir) / "runs" / slug
        if create:
            self.root.mkdir(parents=True, exist_ok=True)

    # -- reading
    def latest_id(self) -> str | None:
        p = self.root / "latest.json"
        if not p.exists():
            return None
        try:
            rid = json.loads(p.read_text(encoding="utf-8")).get("run_id")
        except (json.JSONDecodeError, OSError):
            return None
        return rid if rid and (self.root / rid).is_dir() else None

    def runs(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and not p.name.endswith((".tmp", ".failed")))

    def path(self, run_id: str) -> Path:
        return self.root / run_id

    def metadata(self, run_id: str | None = None) -> dict | None:
        rid = run_id or self.latest_id()
        p = self.path(rid) / "metadata.json" if rid else None
        return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else None

    def load_table(self, run_id: str | None = None) -> pd.DataFrame | None:
        rid = run_id or self.latest_id()
        p = self.path(rid) / "barris.csv" if rid else None
        return pd.read_csv(p) if p and p.exists() else None

    def latest_finished(self):
        md = self.metadata()
        if not md or not md.get("finished_utc"):
            return None
        return datetime.fromisoformat(md["finished_utc"])

    # -- writing
    def begin(self) -> tuple[str, Path]:
        rid = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        tmp = self.root / f"{rid}.tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        return rid, tmp

    def commit(self, run_id: str) -> Path:
        final = self.root / run_id
        os.replace(self.root / f"{run_id}.tmp", final)
        _atomic_write(self.root / "latest.json", json.dumps({"run_id": run_id}))
        return final

    def fail(self, run_id: str) -> Path:
        """Keep a rejected run for diagnosis (checks.json, metadata) but never serve it."""
        src, dst = self.root / f"{run_id}.tmp", self.root / f"{run_id}.failed"
        if dst.exists():
            shutil.rmtree(dst)
        os.replace(src, dst)
        return dst

    def prune(self, keep: int = 6, keep_failed: int = 3) -> list[str]:
        removed = []
        live = self.latest_id()
        for rid in self.runs()[:-keep] if keep > 0 else []:
            if rid != live:
                shutil.rmtree(self.path(rid), ignore_errors=True)
                removed.append(rid)
        failed = sorted(p for p in self.root.iterdir() if p.is_dir() and p.name.endswith(".failed"))
        for p in failed[:-keep_failed] if keep_failed > 0 else failed:
            shutil.rmtree(p, ignore_errors=True)
            removed.append(p.name)
        return removed
