from __future__ import annotations

import time

from app.services.rate_limit import TokenBucketLimiter


def test_capacity_allows_burst_then_blocks() -> None:
    limiter = TokenBucketLimiter(capacity=3, refill_per_second=1000)  # refill irrelevant here
    # Pin the clock so refill can't sneak in between calls.
    t = [0.0]
    limiter._now = lambda: t[0]  # type: ignore[method-assign]

    assert limiter.try_acquire("u") is True
    assert limiter.try_acquire("u") is True
    assert limiter.try_acquire("u") is True
    assert limiter.try_acquire("u") is False


def test_refill_grants_after_wait() -> None:
    limiter = TokenBucketLimiter(capacity=1, refill_per_second=10.0)
    t = [0.0]
    limiter._now = lambda: t[0]  # type: ignore[method-assign]

    assert limiter.try_acquire("u") is True
    assert limiter.try_acquire("u") is False
    t[0] += 0.2  # 0.2 s * 10/s = 2 tokens (capped at 1)
    assert limiter.try_acquire("u") is True


def test_buckets_are_per_key() -> None:
    limiter = TokenBucketLimiter(capacity=1, refill_per_second=0.001)
    assert limiter.try_acquire("a") is True
    assert limiter.try_acquire("a") is False
    assert limiter.try_acquire("b") is True  # different user, fresh bucket


def test_monotonic_real_clock_smoke() -> None:
    # Sanity check that the real clock wiring works end-to-end.
    limiter = TokenBucketLimiter(capacity=1, refill_per_second=1000.0)
    assert limiter.try_acquire("u") is True
    time.sleep(0.01)
    assert limiter.try_acquire("u") is True
