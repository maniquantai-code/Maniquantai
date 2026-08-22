"""ManiQuantAI Backend — FastAPI entry point."""
from __future__ import annotations
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import (llm_router,chat_router,strategies_router,pipeline_router,wallet_router,broker_accounts_router,mt5_bridge_router,paper_decision_router)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
app=FastAPI(title="ManiQuantAI API",version="0.3.0",description="AI-assisted trading strategy platform backend.")
app.add_middleware(CORSMiddleware,allow_origins=["https://maniquantai.vercel.app","https://maniquantai-maniquant-ai.vercel.app","http://localhost:3000"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(llm_router);app.include_router(chat_router);app.include_router(strategies_router);app.include_router(pipeline_router);app.include_router(wallet_router);app.include_router(broker_accounts_router);app.include_router(mt5_bridge_router);app.include_router(paper_decision_router)
@app.get("/")
async def root(): return {"service":"ManiQuantAI API","status":"ok","version":"0.3.0"}
@app.get("/health")
async def health(): return {"status":"ok"}
