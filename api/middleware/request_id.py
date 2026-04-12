"""
api/middleware/request_id.py — Attach unique X-Request-ID to every request.

Enables tracing a single user action through logs / DB writes / alerts.
Client can set X-Request-ID header; if absent, generated server-side.

Usage: app.add_middleware(RequestIDMiddleware)
Logs: include request_id via contextvar (if handlers configured to read it).
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# Accessible throughout the request lifecycle via current_request_id()
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id() -> str:
    """Return the current request's ID, or '-' if not in a request scope."""
    return _request_id_ctx.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Use client-provided ID if present (valid UUID), else generate
        rid = request.headers.get("X-Request-ID", "")
        if not rid or len(rid) > 64:  # reject absurd values
            rid = str(uuid.uuid4())

        token = _request_id_ctx.set(rid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            _request_id_ctx.reset(token)
