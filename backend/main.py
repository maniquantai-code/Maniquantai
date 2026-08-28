"""ManiQuantAI Backend — FastAPI entry point v2 (Agent Team)."""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routers import (
    llm_router, chat_router, strategies_router, pipeline_router,
    wallet_router, broker_accounts_router, mt5_bridge_router,
    live_engine_router, paper_decision_router, strategy_compiler_router,
    live_trading_router,
)
from .routers import auth as auth_module
from .routers import chat as chat_module

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
logger = logging.getLogger("maniquantai")

app = FastAPI(
    title="ManiQuantAI API",
    version="2.0.0",
    description="Professional AI trading agent team platform — live crypto execution through MT5.",
)

chat_module.ANON = auth_module.SUPABASE_ANON_KEY

origins = [
    "https://maniquantai.vercel.app",
    "https://maniquantai-maniquant-ai.vercel.app",
    "http://localhost:3000",
]
extra = os.getenv("FRONTEND_URL")
if extra and extra not in origins:
    origins.append(extra.rstrip("/"))

app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled exception rid=%s path=%s", request_id, request.url.path)
        return JSONResponse(status_code=500, content={"ok": False, "code": "INTERNAL_ERROR", "message": "The service encountered a temporary error. No trading action was executed.", "recoverable": True, "request_id": request_id})
    response.headers["x-request-id"] = request_id
    return response

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"ok": False, "code": "INVALID_REQUEST", "message": "The request could not be processed.", "recoverable": True})

# Core routers
app.include_router(llm_router)
app.include_router(chat_router)
app.include_router(strategies_router)
app.include_router(pipeline_router)
app.include_router(wallet_router)
app.include_router(broker_accounts_router)
app.include_router(mt5_bridge_router)
app.include_router(live_engine_router)
app.include_router(paper_decision_router)
app.include_router(strategy_compiler_router)
# v2 Agent Team router
app.include_router(live_trading_router)

@app.get("/")
async def root():
    return {"service": "ManiQuantAI API", "status": "ok", "version": "2.0.0", "agents": ["momentum", "mean_reversion", "breakout", "scalper", "sentiment", "portfolio_manager"]}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "maniquantai-api", "workflow": "deterministic", "live_engine": "enabled", "agent_team": "6-agent"}
