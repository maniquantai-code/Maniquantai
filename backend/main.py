"""
ManiQuantAI Backend — FastAPI entry point.
Run: uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.health_monitor import run_health_monitor
from .routers import (
    llm_router,
    chat_router,
    strategies_router,
    wallet_router,
    broker_accounts_router,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

app = FastAPI(
    title="ManiQuantAI API",
    version="0.1.0",
    description="AI-assisted crypto trading platform backend.",
)

# CORS — allow the Next.js frontend (and local dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://maniquantai.vercel.app",
        "https://maniquantai-maniquant-ai.vercel.app",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(llm_router)
app.include_router(chat_router)
app.include_router(strategies_router)
app.include_router(wallet_router)
app.include_router(broker_accounts_router)


@app.get("/")
async def root():
    return {"service": "ManiQuantAI API", "status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event():
    """Launch the background health monitor when the server starts."""
    asyncio.create_task(run_health_monitor())
    logging.getLogger("main").info(
        "ManiQuantAI backend started — LLM health monitor running."
    )
