"""Per-user in-process token-bucket rate limiter.

This is defense-in-depth on top of the monthly quota. It catches a runaway
client (buggy extension, accidental loop) before it burns through the month's
budget in minutes. The quota is the user-facing limit; this is the abuse
ceiling.

In-process means each Fly machine has its own buckets. That's acceptable
because (a) we run one machine most of the time, and (b) the real ceiling is
the monthly quota, which IS shared state in Supabase. If we later scale
horizontally and need coordinated limits, swap the bucket store for Redis
without changing callers.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketLimiter:
    def __init__(self, capacity: int, refill_per_second: float) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if refill_per_second <= 0:
            raise ValueError("refill_per_second must be > 0")
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        return time.monotonic()

    def try_acquire(self, key: str, *, cost: float = 1.0) -> bool:
        """Return True if a token was granted, False if the bucket is empty."""
        with self._lock:
            now = self._now()
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(self.capacity), updated_at=now)
                self._buckets[key] = bucket
            else:
                elapsed = now - bucket.updated_at
                bucket.tokens = min(
                    float(self.capacity),
                    bucket.tokens + elapsed * self.refill_per_second,
                )
                bucket.updated_at = now
            if bucket.tokens < cost:
                return False
            bucket.tokens -= cost
            return True

    def reset(self) -> None:
        """Clear all buckets. Test hook."""
        with self._lock:
            self._buckets.clear()
