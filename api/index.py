"""Vercel Python entrypoint for the ManiQuantAI FastAPI backend.

The frontend and backend share one Vercel project. Vercel routes /api/* to
this function, while FastAPI itself owns the /api/... endpoints. The route
capture is passed as __path so the function preserves the original API path.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode

from backend.main import app as _fastapi_app


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

        # Vercel rewrites /api/<path> to /api/index.py?__path=/<path>.
        # Restore the original FastAPI path before dispatching.
        if target is not None:
            if not target.startswith("/"):
                target = "/" + target
            scope = dict(scope)
            scope["path"] = target
            scope["raw_path"] = target.encode("utf-8")
            scope["query_string"] = urlencode(kept, doseq=True).encode("utf-8")

    await _fastapi_app(scope, receive, send)


__all__ = ["app"]
