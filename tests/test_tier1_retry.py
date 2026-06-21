"""Tests for the with_retry() decorator in tier1_extract."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from tier1_extract import with_retry


def test_with_retry_succeeds_on_first_try():
    """with_retry returns immediately when fn succeeds on the first attempt."""
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = with_retry(fn, max_retries=3, delay=0)
    assert result == "ok"
    assert call_count == 1


def test_with_retry_retries_on_timeout():
    """with_retry retries on TimeoutError and eventually returns the successful result."""
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise TimeoutError("timed out")
        return "recovered"

    result = with_retry(fn, max_retries=3, delay=0)
    assert result == "recovered"
    assert call_count == 3


def test_with_retry_propagates_non_transient():
    """with_retry does not retry on non-transient errors like ValueError."""
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        raise ValueError("bad input")

    try:
        with_retry(fn, max_retries=3, delay=0)
        assert False, "Should have raised"
    except ValueError:
        pass
    assert call_count == 1
