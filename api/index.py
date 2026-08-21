"""Vercel Python entrypoint for the ManiQuantAI FastAPI backend.

Vercel's Python runtime exposes files under /api as functions. Keeping a
conventional api/index.py entrypoint makes /api/* reliably reach the FastAPI
application while the Next.js app continues to serve the frontend.
"""

from backend.main import app

__all__ = ["app"]
