"""Vercel Python entrypoint for the ManiQuantAI FastAPI backend.

The frontend and backend share one Vercel project. Vercel routes /api/* to
this function. The FastAPI routers use /api/... prefixes, while health/docs
are mounted at the backend root, so the wrapper restores the right path.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode

from backend.main import app as _fastapi_app

_ROOT_ROUTES = {"/", "/health", "/docs", "/redoc", "/openapi.json"}


async def app(scope, receive, send):
    if scope.get("type") == "http":
        query = scope.get("query_string", b"").decode("utf-8", "ignore")
        params = parse_qsl(query, keep_blank_values=True)
        target = None
        kept: list[tuple[str, str]] = []
        for key, value in params:
            if key == "__path" and target is None:
                target = value or "/"
            else:
                kept.append((key, value))

        if target is not None:
            if not target.startswith("/"):
                target = "/" + target
            # Vercel captures /api/<path> as <path>. Most ManiQuantAI API
            # routers are mounted under /api, while health/docs are root paths.
            if target not in _ROOT_ROUTES and not target.startswith("/api/"):
                target = "/api" + target

            scope = dict(scope)
            scope["path"] = target
            scope["raw_path"] = target.encode("utf-8")
            scope["query_string"] = urlencode(kept, doseq=True).encode("utf-8")

    await _fastapi_app(scope, receive, send)


__all__ = ["app"]
