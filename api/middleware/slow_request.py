"""
api/middleware/slow_request.py — log a WARNING when a request takes
longer than `SLOW_REQUEST_MS` (env, default 500 ms).

Purely additive — never blocks, never modifies the response. Useful for
catching backend slowdowns that don't trip the existing scan_duration
metric (e.g. analytical endpoints under load, ad-hoc tooling calls).

Logfire's FastAPI integration already records full traces; this is a
log-line-level shortcut so the slow request shows up in `logs/api.log`
without needing a Logfire token.

Usage in api/main.py:
    from api.middleware.slow_request import SlowRequestMiddleware
    app.add_middleware(SlowRequestMiddleware)
"""
from __future__ import annotations

import os
import time
from typing import Any

from src.core.logger import logger


class SlowRequestMiddleware:
    """Pure-ASGI middleware — same approach as RequestIDMiddleware to
    survive WebSocket / SSE without choking on Starlette's HTTPMiddleware
    quirks."""

    def __init__(self, app: Any):
        self.app = app
        try:
            self.threshold_s = max(0.05, float(os.environ.get("SLOW_REQUEST_MS", "500")) / 1000.0)
        except (TypeError, ValueError):
            self.threshold_s = 0.5

    async def __call__(self, scope, receive, send):
        # Only time HTTP requests — WebSockets and lifespan don't have a
        # meaningful "duration" for this purpose.
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Skip the noisy endpoints — health and SSE are intentionally
        # long-lived or extremely frequent.
        path = scope.get("path", "")
        if path.startswith("/api/health") or path.startswith("/api/sse/"):
            return await self.app(scope, receive, send)

        method = scope.get("method", "?")
        start = time.perf_counter()
        status_code: int | None = None

        async def _send_with_capture(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status")
            await send(message)

        try:
            await self.app(scope, receive, _send_with_capture)
        finally:
            elapsed = time.perf_counter() - start
            if elapsed >= self.threshold_s:
                logger.warning(
                    f"⏱️ SLOW {method} {path} — {elapsed * 1000:.0f} ms "
                    f"(status={status_code or '?'} threshold={self.threshold_s * 1000:.0f}ms)"
                )
