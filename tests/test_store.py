import json

from greenspace.store import RunStore


def test_commit_makes_run_live_atomically(tmp_path):
    s = RunStore(tmp_path, "x")
    assert s.latest_id() is None
    rid, d = s.begin()
    (d / "barris.csv").write_text("barri_code\n1\n")
    assert s.latest_id() is None                      # still a .tmp dir: invisible to readers
    s.commit(rid)
    assert s.latest_id() == rid and s.runs() == [rid]
    assert s.load_table()["barri_code"].tolist() == [1]


def test_failed_run_is_kept_but_never_served(tmp_path):
    s = RunStore(tmp_path, "x")
    rid, d = s.begin()
    (d / "checks.json").write_text("[]")
    s.fail(rid)
    assert s.latest_id() is None and s.runs() == []
    assert (s.root / f"{rid}.failed" / "checks.json").exists()


def test_prune_keeps_live_and_recent(tmp_path):
    s = RunStore(tmp_path, "x")
    ids = []
    for i in range(5):
        rid = f"2026010{i}T000000Z"
        (s.root / f"{rid}.tmp").mkdir()
        s.commit(rid)
        ids.append(rid)
    s.prune(keep=2)
    assert s.runs() == ids[-2:] and s.latest_id() == ids[-1]


def test_corrupt_latest_pointer_is_ignored(tmp_path):
    s = RunStore(tmp_path, "x")
    (s.root / "latest.json").write_text("{not json")
    assert s.latest_id() is None
    (s.root / "latest.json").write_text(json.dumps({"run_id": "missing"}))
    assert s.latest_id() is None


def test_read_only_store_does_not_create_dirs(tmp_path):
    s = RunStore(tmp_path / "nope", "x", create=False)
    assert s.latest_id() is None and s.runs() == [] and not (tmp_path / "nope").exists()
