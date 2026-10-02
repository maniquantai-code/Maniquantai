"""HTTP/API security middleware for ManiQuantAI."""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "120"))
_WINDOW = 60.0


class SecurityMiddleware(BaseHTTPMiddleware):
    """Adds security headers and a lightweight per-instance request limiter.

    The limiter is intentionally only a first layer; production deployments
    should also use an edge/WAF rate limit because serverless instances do not
    share memory.
    """

    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        now = time.monotonic()
        key = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
            request.client.host if request.client else "unknown"
        )
        q = self._hits[key]
        while q and now - q[0] > _WINDOW:
            q.popleft()
        if len(q) >= _RATE_LIMIT:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        q.append(now)

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else response.headers.get("Cache-Control", "public, max-age=0")
        response.headers["X-Request-ID"] = request.headers.get("x-request-id", "")
        return response
