"""
api/middleware/auth.py — API Key authentication for write endpoints

Simple API key auth via X-API-Key header or ?api_key query param.
Key is configured in .env as API_SECRET_KEY.

Protected: all POST/PUT/DELETE endpoints under /api/.
Unprotected: GET endpoints (read-only), /api/health, WebSocket.

Usage in main.py:
    from api.middleware.auth import ApiKeyMiddleware
    app.add_middleware(ApiKeyMiddleware)
"""

import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Load API key from environment
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")

# Endpoints that are always public (no auth required)
PUBLIC_PATHS = {
    "/api/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# Methods that require authentication
PROTECTED_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Require API key for write operations on /api/* endpoints."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # Skip auth if no API key configured (backwards compatible)
        if not API_SECRET_KEY:
            return await call_next(request)

        # Skip non-API paths and public endpoints
        if not path.startswith("/api/") or path in PUBLIC_PATHS:
            return await call_next(request)

        # Skip read-only methods
        if method not in PROTECTED_METHODS:
            return await call_next(request)

        # Skip WebSocket
        if "upgrade" in request.headers.get("connection", "").lower():
            return await call_next(request)

        # Check API key
        api_key = (
            request.headers.get("X-API-Key")
            or request.query_params.get("api_key")
        )

        if api_key != API_SECRET_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key. Set X-API-Key header."},
            )

        return await call_next(request)
