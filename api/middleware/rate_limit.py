"""
api/middleware/rate_limit.py — Lightweight in-process rate limiter

Token bucket algorithm per client IP + endpoint.
No external dependencies (no slowapi/Redis needed).

Usage in main.py:
    from api.middleware.rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)
"""

import time
import threading
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# Per-route rate limits: (max_requests, window_seconds)
RATE_LIMITS = {
    "/api/portfolio/quick-trade":   (3, 60),      # 3 per minute
    "/api/portfolio/add-trade":     (5, 60),       # 5 per minute
    "/api/portfolio/update-balance": (3, 60),      # 3 per minute
    "/api/risk/halt":               (5, 60),       # 5 per minute
    "/api/risk/resume":             (5, 60),       # 5 per minute
    "/api/agent/chat":              (10, 60),      # 10 per minute
    "/api/training/start":          (2, 300),      # 2 per 5 minutes
    "/api/analysis/quant-pro":      (10, 60),      # 10 per minute
}

# Default limit for unspecified endpoints
DEFAULT_LIMIT = (30, 60)  # 30 per minute

# Cleanup interval for stale entries
CLEANUP_INTERVAL = 300  # 5 minutes


class TokenBucket:
    """Simple token bucket rate limiter."""

    def __init__(self, max_tokens: int, refill_seconds: float):
        self.max_tokens = max_tokens
        self.refill_rate = max_tokens / refill_seconds  # tokens per second
        self.tokens = float(max_tokens)
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        """Try to consume one token. Returns True if allowed, False if rate limited."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    @property
    def retry_after(self) -> float:
        """Seconds until next token is available."""
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.refill_rate


class _RateLimitHTTPMiddleware(BaseHTTPMiddleware):
    """Inner HTTP-only rate limiter."""

    def __init__(self, app):
        super().__init__(app)
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def _get_bucket(self, key: str, max_req: int, window: float) -> TokenBucket:
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(max_req, window)
            return self._buckets[key]

    def _cleanup_stale(self):
        """Remove buckets that haven't been used recently."""
        now = time.monotonic()
        if now - self._last_cleanup < CLEANUP_INTERVAL:
            return
        with self._lock:
            stale = [k for k, b in self._buckets.items()
                     if now - b.last_refill > CLEANUP_INTERVAL]
            for k in stale:
                del self._buckets[k]
            self._last_cleanup = now

    async def dispatch(self, request: Request, call_next):
        # Only rate-limit API endpoints
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        # Skip health checks
        if path == "/api/health":
            return await call_next(request)

        # Get client IP
        client_ip = request.client.host if request.client else "unknown"

        # Find matching rate limit
        max_req, window = DEFAULT_LIMIT
        for route_prefix, limits in RATE_LIMITS.items():
            if path.startswith(route_prefix):
                max_req, window = limits
                break

        # Check rate limit
        bucket_key = f"{client_ip}:{path}"
        bucket = self._get_bucket(bucket_key, max_req, window)

        if not bucket.consume():
            retry_after = int(bucket.retry_after) + 1
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        # Periodic cleanup
        self._cleanup_stale()

        response = await call_next(request)
        return response


class RateLimitMiddleware:
    """Pure ASGI wrapper — bypasses WebSocket, delegates HTTP to BaseHTTPMiddleware."""

    def __init__(self, app):
        self._app = app
        self._http = _RateLimitHTTPMiddleware(app)

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("websocket", "lifespan"):
            await self._app(scope, receive, send)
        else:
            await self._http(scope, receive, send)
