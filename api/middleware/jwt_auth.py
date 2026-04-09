"""
api/middleware/jwt_auth.py — JWT + API Key Authentication Middleware

Supports 3 authentication methods (checked in order):
  1. Bearer token: Authorization: Bearer <jwt_token>
  2. API key header: X-API-Key: <user_api_key>
  3. Legacy API_SECRET_KEY from .env (backwards compatible)

Protected: all POST/PUT/DELETE on /api/* endpoints.
Public: GET endpoints, /api/auth/*, /api/health, /docs.

Sets request.state.user with user context if authenticated.
"""

import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Legacy API key from .env (backwards compatible with Phase 4 auth)
_LEGACY_KEY = os.getenv("API_SECRET_KEY", "")

# Endpoints always public (no auth required)
_PUBLIC_PATHS = {"/api/health", "/docs", "/openapi.json", "/redoc"}
_PUBLIC_PREFIXES = ("/api/auth/",)  # registration + login

# Methods requiring authentication
_PROTECTED_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


class JwtAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate requests via JWT, API key, or legacy key."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # Always allow non-API, public paths, GET, WebSocket
        if (not path.startswith("/api/")
                or path in _PUBLIC_PATHS
                or any(path.startswith(p) for p in _PUBLIC_PREFIXES)
                or method not in _PROTECTED_METHODS
                or "upgrade" in request.headers.get("connection", "").lower()):
            return await call_next(request)

        # --- Try authentication methods ---
        user = None

        # Method 1: Bearer JWT token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                from src.auth import decode_token, get_user_by_id
                payload = decode_token(token)
                if payload:
                    user = get_user_by_id(payload["user_id"])
            except (ImportError, KeyError, TypeError):
                pass

        # Method 2: X-API-Key header (user-specific API key)
        if user is None:
            api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
            if api_key:
                # Check if it's a user API key (starts with qs_)
                if api_key.startswith("qs_"):
                    try:
                        from src.auth import get_user_by_api_key
                        user = get_user_by_api_key(api_key)
                    except (ImportError, AttributeError):
                        pass

                # Method 3: Legacy API_SECRET_KEY from .env
                if user is None and _LEGACY_KEY and api_key == _LEGACY_KEY:
                    user = {"user_id": 0, "username": "admin", "role": "admin"}

        # No auth configured at all → allow (backwards compatible)
        if not _LEGACY_KEY and user is None:
            # No auth system configured → passthrough (development mode)
            return await call_next(request)

        if user is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required. Use Bearer token or X-API-Key header."},
            )

        # Set user context on request state
        request.state.user = user
        return await call_next(request)
