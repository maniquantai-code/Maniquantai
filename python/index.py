"""ManiQuantAI — Vercel Python entrypoint at /python/index.py"""
from __future__ import annotations
import json, traceback
from urllib.parse import parse_qsl, urlencode

_app = None
_import_error = None

try:
    from backend.main import app as _fastapi_app
    _app = _fastapi_app
except Exception:
    _import_error = traceback.format_exc()

async def app(scope, receive, send):
    if scope.get("type") != "http":
        if _app:
            await _app(scope, receive, send)
        return

    # Extract __path from query string and set as the request path
    query = scope.get("query_string", b"").decode("utf-8", "ignore")
    params = parse_qsl(query, keep_blank_values=True)
    target = None
    kept = []
    for key, value in params:
        if key == "__path" and target is None:
            target = value or "/"
        else:
            kept.append((key, value))

    if target:
        if not target.startswith("/"):
            target = "/" + target
        scope = dict(scope)
        scope["path"] = target
        scope["raw_path"] = target.encode("utf-8")
        scope["query_string"] = urlencode(kept).encode("utf-8")

    if _app is None:
        body = json.dumps({"ok": False, "error": "Backend startup failed", "detail": _import_error}).encode()
        await send({"type": "http.response.start", "status": 500,
                    "headers": [[b"content-type", b"application/json"],
                                [b"access-control-allow-origin", b"*"]]})
        await send({"type": "http.response.body", "body": body})
        return

    await _app(scope, receive, send)

__all__ = ["app"]
