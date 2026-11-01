"""Retry with exponential backoff for flaky public APIs (Overpass answers 502/504 when busy)."""
import logging
import time

log = logging.getLogger(__name__)


def call_with_retry(fn, tries: int = 5, base_delay: float = 20.0, max_delay: float = 240.0,
                    sleep_fn=time.sleep, what: str = "call"):
    """Call fn(attempt_index) until it succeeds; wait base_delay * 2**i (capped) between attempts."""
    last = None
    for i in range(tries):
        try:
            return fn(i)
        except Exception as e:
            last = e
            if i == tries - 1:
                break
            delay = min(base_delay * 2 ** i, max_delay)
            msg = (str(e).strip().splitlines() or [""])[0][:120]
            log.warning("%s failed (%s: %s) - retry %d/%d in %.0fs", what, type(e).__name__, msg, i + 1, tries - 1, delay)
            sleep_fn(delay)
    raise last
