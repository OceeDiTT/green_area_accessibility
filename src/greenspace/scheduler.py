"""Tiny dependency-free scheduler: re-run the pipeline when the live run is older than N days."""
import logging
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def is_due(last_finished: datetime | None, every_days: float, now: datetime) -> bool:
    if last_finished is None:
        return True
    if last_finished.tzinfo is None:
        last_finished = last_finished.replace(tzinfo=timezone.utc)
    return now - last_finished >= timedelta(days=every_days)


def run_forever(job, store, every_days: float, poll_seconds: float = 3600, retry_seconds: float = 6 * 3600,
                now_fn=lambda: datetime.now(timezone.utc), sleep_fn=time.sleep, max_iterations: int | None = None) -> int:
    """Poll; run `job()` when due. State lives in the run store, so container restarts do not trigger extra runs."""
    runs = 0
    i = 0
    while max_iterations is None or i < max_iterations:
        i += 1
        wait = poll_seconds
        if is_due(store.latest_finished(), every_days, now_fn()):
            log.info("Live run is missing or older than %s days - starting pipeline", every_days)
            try:
                job()
                runs += 1
            except Exception:
                log.exception("Scheduled run failed; retrying in %.0f s", retry_seconds)
                wait = retry_seconds
        sleep_fn(wait)
    return runs
