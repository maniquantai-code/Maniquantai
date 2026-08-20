"""Strategy-aware chat orchestration with deterministic pipeline actions."""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from ..core.llm_router import router as llm_router
from .auth import get_current_user
from .pipeline import run_pipeline

api_router = APIRouter(prefix="/api", tags=["chat"])
SUPABASE_URL = "https://zuimeyynaarjsovnqilk.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X"
SYSTEM_PROMPT = """You are ManiQuantAI's trading assistant. Interpret the user's strategy request and explain the deterministic pipeline state supplied by the backend. Never invent backtest, paper-trading, win-rate, drawdown, P&L, or trade-count numbers. If a metric is absent, say it is not available yet."""

class ChatRequest(BaseModel):
    strategy_id: str
    message: str

def _headers(token: str):
    return {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}

async def _load_strategy(strategy_id: str, user_id: str, token: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/strategies",
            headers=_headers(token),
            params={
                "strategy_id": f"eq.{strategy_id}",
                "user_id": f"eq.{user_id}",
                "select": "strategy_id,name,raw_strategy_text,status,spec",
                "limit": "1",
            },
        )
    if not r.is_success:
        raise HTTPException(502, "Could not load strategy state")
    rows = r.json()
    if not rows:
        raise HTTPException(404, "Strategy not found")
    return rows[0]

async def _save_state(strategy_id, user_id, token, spec, status=None):
    payload = {"spec": spec}
    if status:
        payload["status"] = status
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(
            f"{SUPABASE_URL}/rest/v1/strategies",
            headers=_headers(token),
            params={"strategy_id": f"eq.{strategy_id}", "user_id": f"eq.{user_id}"},
            json=payload,
        )
    if not r.is_success:
        raise HTTPException(502, "Could not persist pipeline state")

def _norm(t):
    return re.sub(r"\s+", " ", t.strip().lower())

def _is_yes(t):
    return _norm(t) in {"yes", "y", "confirm", "confirmed", "proceed", "go ahead", "do it"}

def _is_approve(t):
    return _norm(t) in {"approve", "approved", "approve it", "confirm approval"}

def _is_paper(t):
    return "paper trading" in _norm(t) or "paper trade" in _norm(t)

def _is_paper_launch(t):
    return _norm(t) in {"do paper trade", "start paper trade", "launch paper trading", "launch paper trade"}

def _looks_like_backtest(t):
    v = _norm(t)
    return "backtest" in v or ("last 90 days" in v and ("btc" in v or "bitcoin" in v))

def _looks_like_strategy_request(t):
    v = _norm(t)
    indicators = ("rsi", "bollinger", "ema", "sma", "macd", "atr", "adx", "stochastic", "moving average", "mean reversion", "breakout", "crossover")
    return any(x in v for x in indicators) and any(x in v for x in ("buy", "sell", "enter", "exit", "trade", "strategy"))

def _context(strategy, state):
    metrics = state.get("backtest", {}).get("metrics") or {}
    return (
        f"Strategy: {strategy.get('name') or 'Untitled'}\n"
        f"Spec: {strategy.get('raw_strategy_text') or ''}\n"
        f"Pipeline stage: {state.get('pipeline_stage', 'research')}\n"
        f"Pending: {state.get('pending_confirmation') or 'none'}\n"
        f"Agents: {json.dumps(state.get('agents') or {})}\n"
        f"Backtest metrics: {json.dumps(metrics) if metrics else 'none'}\n"
        f"Paper session: {json.dumps(state.get('paper_session')) if state.get('paper_session') else 'none'}"
    )

def _action(message, state):
    text = _norm(message)
    pending = state.get("pending_confirmation")
    if _is_yes(text) and pending in {"backtest", "backtest_review"}:
        state["pending_confirmation"] = None
        state["pipeline_stage"] = "backtest_running"
        state.setdefault("backtest", {})["status"] = "queued"
        return "backtest", "Confirmed. The deterministic backtest is starting now. I will report only metrics produced by the backtest engine."
    if _is_approve(text):
        state["approved"] = True
        state["approved_at"] = datetime.now(timezone.utc).isoformat()
        state["pipeline_stage"] = "paper_ready"
        state["pending_confirmation"] = None
        return "approve", "Approved. The strategy passed the human-approval gate. Paper trading is now the next gated stage."
    if _is_paper_launch(text) and state.get("approved"):
        state["paper_session"] = {"status": "running", "mode": "paper", "started_at": datetime.now(timezone.utc).isoformat(), "initial_capital": 10000, "risk_per_trade": 0.01, "max_concurrent_positions": 1}
        state["pipeline_stage"] = "paper_trading"
        state["agents"] = {**state.get("agents", {}), "paper": "running"}
        return "paper_launch", "Paper trading has been launched with the saved strategy configuration. No live capital is used."
    if _is_paper(text):
        if state.get("approved"):
            state["pipeline_stage"] = "paper_ready"
            state["pending_confirmation"] = "paper_launch"
            return "paper_ready", "Paper trading is ready. Say “do paper trade” to launch it using this strategy."
        return None, "Paper trading is gated until backtesting and human approval are complete."
    if _looks_like_backtest(message):
        state["pipeline_stage"] = "backtest_ready"
        state["pending_confirmation"] = "backtest"
        return "backtest_request", "I have the strategy and backtest request. Say “yes” and I’ll run the deterministic backtest."
    return None, None

@api_router.post("/chat")
async def strategy_chat(req: ChatRequest, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    token = user.get("_access_token")
    if not token:
        raise HTTPException(401, "Missing access token")
    strategy = await _load_strategy(req.strategy_id, user["id"], token)
    state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
    action, response = _action(req.message, state)
    if response and action in {"backtest", "backtest_request", "approve", "paper_ready", "paper_launch"}:
        if action == "backtest":
            state["agents"] = {**state.get("agents", {}), "research": "complete", "backtest": "queued"}
            background_tasks.add_task(run_pipeline, req.strategy_id, user["id"], token)
        await _save_state(req.strategy_id, user["id"], token, state, "backtesting" if action == "backtest" else None)
        async def stream():
            yield f"data: {json.dumps({'type': 'delta', 'content': response})}\n\n"
            yield f"data: {json.dumps({'type': 'state', 'pipeline_stage': state.get('pipeline_stage'), 'action': action})}\n\n"
            yield "data: {\"type\":\"done\",\"deterministic\":true}\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\nCurrent state:\n" + _context(strategy, state)}, {"role": "user", "content": req.message}]
    async def event_stream():
        try:
            async for event in llm_router.stream_chat(messages=messages, max_tokens=256, temperature=0.1):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': f'LLM service failed: {exc}'})}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
