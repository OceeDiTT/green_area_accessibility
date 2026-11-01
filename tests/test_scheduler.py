from datetime import datetime, timedelta, timezone

from greenspace.scheduler import is_due, run_forever
from helpers import write_run

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def test_is_due():
    assert is_due(None, 30, NOW)
    assert not is_due(NOW - timedelta(days=10), 30, NOW)
    assert is_due(NOW - timedelta(days=31), 30, NOW)
    assert not is_due(datetime(2026, 10, 30), 30, NOW)          # naive timestamps are treated as UTC


def test_runs_when_no_data_then_waits(tmp_path):
    from greenspace.store import RunStore
    store = RunStore(tmp_path, "barcelona")
    calls = []
    sleeps = []

    def job():
        calls.append(1)
        write_run(tmp_path)

    n = run_forever(job, store, 30, now_fn=lambda: datetime(2026, 11, 2, tzinfo=timezone.utc),
                    sleep_fn=sleeps.append, max_iterations=3)
    assert n == 1 and len(calls) == 1 and len(sleeps) == 3        # fresh data after the 1st run -> no more runs


def test_failed_job_backs_off_and_does_not_crash(tmp_path):
    from greenspace.store import RunStore
    store = RunStore(tmp_path, "barcelona")
    sleeps = []

    def job():
        raise RuntimeError("API down")

    n = run_forever(job, store, 30, poll_seconds=10, retry_seconds=99, sleep_fn=sleeps.append, max_iterations=2)
    assert n == 0 and sleeps == [99, 99]
