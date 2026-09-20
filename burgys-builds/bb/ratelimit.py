"""A sliding-window rate limiter, per client and per scope."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    def __init__(self, per_minute: int = 120) -> None:
        self.per_minute = max(1, int(per_minute))
        self._hits: dict = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> tuple:
        """``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > 60.0:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return False, max(1, int(61 - (now - hits[0])))
            hits.append(now)
            return True, 0
