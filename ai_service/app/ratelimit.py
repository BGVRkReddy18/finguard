"""Per-user sliding-window limits for the expensive (LLM-backed) endpoints.

A public demo must not let one visitor burn the whole free-tier LLM quota. In-memory is enough for a
single ai-service process; with several replicas this would move to Redis (same algorithm).
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, status


class UserRateLimiter:
    def __init__(self, limit: int, window_s: int = 3600):
        self.limit, self.window_s = limit, window_s
        self.hits: dict[int, deque[float]] = defaultdict(deque)

    def check(self, user_id: int) -> None:
        if self.limit <= 0:
            return  # disabled
        now = time.monotonic()
        hits = self.hits[user_id]
        while hits and hits[0] <= now - self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            retry = int(hits[0] + self.window_s - now) + 1
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                f"Limit of {self.limit} AI requests per hour reached — try again in {retry // 60 + 1} min.",
                                headers={"Retry-After": str(retry)})
        hits.append(now)
