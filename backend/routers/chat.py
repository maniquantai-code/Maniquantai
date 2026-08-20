"""Strategy-aware chat orchestration."""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from ..core.llm_router import router as llm_router
from .auth import get_current_user
from .pipeline import run_pipeline

api_router = APIRouter(prefix="/api", tags=["chat"])
SUPABASE_URL = "https://zuimeyynaarjsovnqilk.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X"
SYSTEM = "You are ManiQuantAI. Parse strategy requests, never invent trading metrics, and use the deterministic pipeline for research and backtesting."

class ChatRequest(BaseModel):
    strategy_id: str
    message: str

def headers(token):
    return {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}

async def load(sid, uid, token):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/strategies", headers=headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}", "select": "strategy_id,name,raw_strategy_text,status,spec", "limit": "1"})
    if not r.is_success or not r.json():
        raise HTTPException(404, "Strategy not found")
    return r.json()[0]

async def save(sid, uid, token, state, status=None):
    p = {"spec": state}
    if status:
        p["status"] = status
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(f"{SUPABASE_URL}/rest/v1/strategies", headers=headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"}, json=p)
    if not r.is_success:
        raise HTTPException(502, "Could not persist strategy state")

def norm(x):
    return re.sub(r"\s+", " ", x.strip().lower())

def strategy_request(x):
    v = norm(x)
    keys = ("rsi", "bollinger", "ema", "sma", "macd", "atr", "adx", "stochastic", "moving average", "mean reversion", "breakout", "crossover")
    return any(k in v for k in keys) and any(k in v for k in ("buy", "sell", "enter", "exit", "trade", "strategy"))

def backtest_request(x):
    return "backtest" in norm(x)

def yes(x):
    return norm(x) in {"yes", "y", "confirm", "confirmed", "proceed", "go ahead", "do it"}

def approve(x):
    return norm(x) in {"approve", "approved", "approve it"}

def paper(x):
    return "paper trading" in norm(x) or "paper trade" in norm(x)

@api_router.post("/chat")
async def chat(req: ChatRequest, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    token = user.get("_access_token")
    if not token:
        raise HTTPException(401, "Missing access token")
    strategy = await load(req.strategy_id, user["id"], token)
    state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
    text = norm(req.message)
    action = None
    response = None

    if strategy_request(req.message):
        state["pipeline_stage"] = "research_queued"
        state["agents"] = {**state.get("agents", {}), "research": "queued", "backtest": "queued", "indicator": "queued", "paper": "gated", "live": "gated"}
        state["pending_confirmation"] = "backtest_review"
        action = "strategy"
        response = "I’ve understood the strategy. Research and deterministic backtesting are starting now. I’ll show only results produced by the agents."
        await save(req.strategy_id, user["id"], token, state, "research")
        background_tasks.add_task(run_pipeline, req.strategy_id, user["id"], token)
    elif yes(text) and state.get("pending_confirmation") in {"backtest", "backtest_review"}:
        state["pipeline_stage"] = "backtest_running"
        state["pending_confirmation"] = None
        action = "backtest"
        response = "Confirmed. The deterministic backtest is running now."
        await save(req.strategy_id, user["id"], token, state, "backtesting")
        background_tasks.add_task(run_pipeline, req.strategy_id, user["id"], token)
    elif backtest_request(text):
        state["pipeline_stage"] = "backtest_running"
        state["pending_confirmation"] = None
        action = "backtest"
        response = "I’m starting the deterministic backtest for this strategy now."
        await save(req.strategy_id, user["id"], token, state, "backtesting")
        background_tasks.add_task(run_pipeline, req.strategy_id, user["id"], token)
    elif approve(text):
        state["approved"] = True
        state["approved_at"] = datetime.now(timezone.utc).isoformat()
        state["pipeline_stage"] = "paper_ready"
        action = "approve"
        response = "Approved. Paper trading is now the next gated stage."
        await save(req.strategy_id, user["id"], token, state)
    elif paper(text):
        if not state.get("approved"):
            response = "Paper trading is gated until the backtest and human approval gates are complete."
        else:
            state["pipeline_stage"] = "paper_ready"
            state["pending_confirmation"] = "paper_launch"
            action = "paper_ready"
            response = "Paper trading is ready. Say ‘do paper trade’ to launch it using this strategy."
            await save(req.strategy_id, user["id"], token, state)

    if response is not None:
        return JSONResponse({"type": "action", "action": action, "content": response, "pipeline_stage": state.get("pipeline_stage"), "deterministic": True})

    context = f"Strategy: {strategy.get('name')}\nRaw strategy: {strategy.get('raw_strategy_text')}\nPipeline: {state.get('pipeline_stage')}\nAgents: {json.dumps(state.get('agents', {}))}\nBacktest: {json.dumps(state.get('backtest', {}))}"
    messages = [{"role": "system", "content": SYSTEM + "\n\n" + context}, {"role": "user", "content": req.message}]

    async def stream():
        try:
            async for event in llm_router.stream_chat(messages=messages, max_tokens=512, temperature=0.1):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        yield 'data: {"type":"done"}\n\n'

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
