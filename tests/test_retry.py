import pytest
from greenspace.retry import call_with_retry


def test_succeeds_after_transient_failures_with_exponential_backoff():
    waits, calls = [], []

    def flaky(i):
        calls.append(i)
        if i < 2:
            raise RuntimeError("502 Bad Gateway\nserver busy")
        return "ok"

    assert call_with_retry(flaky, tries=5, base_delay=10, sleep_fn=waits.append) == "ok"
    assert calls == [0, 1, 2] and waits == [10, 20]


def test_gives_up_and_raises_the_last_error():
    waits = []

    def always(i):
        raise ValueError(f"fail {i}")

    with pytest.raises(ValueError):
        call_with_retry(always, tries=3, base_delay=1, sleep_fn=waits.append)
    assert waits == [1, 2]


def test_delay_is_capped():
    waits = []

    def always(i):
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        call_with_retry(always, tries=6, base_delay=100, max_delay=250, sleep_fn=waits.append)
    assert waits == [100, 200, 250, 250, 250]


def test_attempt_index_is_passed_so_callers_can_rotate_servers():
    seen = []

    def f(i):
        seen.append(i % 2)
        if i < 3:
            raise RuntimeError("x")

    call_with_retry(f, tries=5, sleep_fn=lambda s: None)
    assert seen == [0, 1, 0, 1]
