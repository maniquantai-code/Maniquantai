"""ManiQuantAI Backend — FastAPI v2"""
from __future__ import annotations
import logging
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("maniquantai")

app = FastAPI(title="ManiQuantAI API", version="2.0.0")

origins = [
    "https://maniquantai.vercel.app",
    "https://maniquantai-maniquant-ai.vercel.app",
    "http://localhost:3000",
]
extra = os.getenv("FRONTEND_URL")
if extra:
    origins.append(extra.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import routers one by one — if one fails, others still work
_routers_loaded = []
_router_errors = []

def _load(name: str, module_path: str, attr: str = "api_router"):
    try:
        import importlib
        mod = importlib.import_module(module_path)
        router = getattr(mod, attr)
        app.include_router(router)
        _routers_loaded.append(name)
    except Exception as e:
        _router_errors.append(f"{name}: {e}")
        logger.error("Failed to load router %s: %s", name, e)

_load("auth",             "backend.routers.auth")
_load("llm",              "backend.routers.llm")
_load("chat",             "backend.routers.chat")
_load("strategies",       "backend.routers.strategies")
_load("pipeline_multi",   "backend.routers.pipeline_multi")
_load("pipeline_mt5",     "backend.routers.pipeline_mt5")
_load("wallet",           "backend.routers.wallet")
_load("broker_accounts",  "backend.routers.broker_accounts")
_load("mt5_bridge",       "backend.routers.mt5_bridge")
_load("live_engine",      "backend.routers.live_engine")
_load("paper_decision",   "backend.routers.paper_decision")
_load("strategy_compiler","backend.routers.strategy_compiler")
_load("live_trading",     "backend.routers.live_trading")

@app.get("/")
async def root():
    return {
        "service": "ManiQuantAI API",
        "status": "ok",
        "version": "2.0.0",
        "routers_loaded": _routers_loaded,
        "router_errors": _router_errors,
    }

@app.get("/health")
async def health():
    return {
        "status": "ok" if not _router_errors else "degraded",
        "routers_loaded": _routers_loaded,
        "router_errors": _router_errors,
    }
