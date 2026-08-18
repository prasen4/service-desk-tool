"""Minimal in-process rate limiting for endpoints that spend LLM budget or
write shared state (config, uploads). Deliberately dependency-free — this is
a single-process app (see DEPLOYMENT.md), so an in-memory sliding window is
sufficient and avoids pulling in a Redis dependency this deployment doesn't
otherwise need. If/when the app scales to multiple instances, this should
move to a shared store (Redis) alongside the job queue.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    """Sliding-window limiter keyed by an arbitrary string (e.g. client IP)."""

    def __init__(self, max_calls: int, period_seconds: float):
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.period_seconds:
                q.popleft()
            if len(q) >= self.max_calls:
                retry_after = self.period_seconds - (now - q[0])
                return False, max(retry_after, 0.0)
            q.append(now)
            return True, 0.0


def _client_key(request: Request) -> str:
    # Respect a trusted reverse proxy's forwarded header if present (nginx sits
    # in front per DEPLOYMENT.md); fall back to the direct peer address.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(limiter: RateLimiter, scope: str):
    """FastAPI dependency factory: raises 429 once ``limiter`` is exceeded."""

    async def _dependency(request: Request) -> None:
        key = f"{scope}:{_client_key(request)}"
        allowed, retry_after = limiter.check(key)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests — please slow down and try again shortly.",
                headers={"Retry-After": str(max(1, int(retry_after) + 1))},
            )

    return _dependency


# Shared limiter instances for expensive / sensitive endpoints.
pipeline_limiter = RateLimiter(max_calls=5, period_seconds=300)      # 5 per 5 min / IP
configure_limiter = RateLimiter(max_calls=10, period_seconds=60)     # 10 per min / IP
upload_limiter = RateLimiter(max_calls=30, period_seconds=60)        # 30 per min / IP
