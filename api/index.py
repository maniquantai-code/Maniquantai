"""ManiQuantAI — Vercel Python entrypoint.
Wraps the FastAPI app. If any import fails, returns a JSON error instead of crashing.
"""
from __future__ import annotations
import json
import traceback
from urllib.parse import parse_qsl, urlencode

_ROOT_ROUTES = {"/", "/health", "/docs", "/redoc", "/openapi.json"}
_app = None
_import_error = None

try:
    from backend.main import app as _fastapi_app
    _app = _fastapi_app
except Exception as e:
    _import_error = traceback.format_exc()

async def app(scope, receive, send):
    if scope.get("type") == "http":
        # Rewrite path
        query = scope.get("query_string", b"").decode("utf-8", "ignore")
        params = parse_qsl(query, keep_blank_values=True)
        target = None
        kept = []
        for key, value in params:
            if key == "__path" and target is None:
                target = value or "/"
            else:
                kept.append((key, value))

        if target is not None:
            if not target.startswith("/"):
                target = "/" + target
            if target not in _ROOT_ROUTES and not target.startswith("/api/"):
                target = "/api" + target
            scope = dict(scope)
            scope["path"] = target
            scope["raw_path"] = target.encode("utf-8")
            scope["query_string"] = urlencode(kept, doseq=True).encode("utf-8")

        # If import failed, return helpful JSON error
        if _app is None:
            body = json.dumps({
                "ok": False,
                "error": "Backend failed to start",
                "detail": _import_error or "Unknown import error",
            }).encode()
            await send({"type": "http.response.start", "status": 500,
                        "headers": [[b"content-type", b"application/json"],
                                    [b"access-control-allow-origin", b"*"]]})
            await send({"type": "http.response.body", "body": body})
            return

    await _app(scope, receive, send)

__all__ = ["app"]
