"""Strategy-aware chat orchestration."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from ..core.llm_router import router as llm_router
from .auth import get_current_user
from .pipeline_mt5 import run_backtest, run_research

api_router = APIRouter(prefix="/api", tags=["chat"])
SUPABASE_URL = "https://zuimeyynaarjsovnqilk.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X"
SYSTEM = "You are ManiQuantAI. Parse strategy requests, never invent trading metrics, and use the deterministic pipeline for research and backtesting. Market data comes from the user's connected MetaTrader 5 account first; the configured fallback is used only when the MT5 feed fails. Never claim a backtest ran unless deterministic pipeline state confirms it. Never contradict the authoritative pipeline state."


class ChatRequest(BaseModel):
    strategy_id: str
    message: str


def headers(token: str) -> dict[str, str]:
    return {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}


async def load(sid: str, uid: str, token: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/strategies", headers=headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}", "select": "strategy_id,name,raw_strategy_text,status,spec", "limit": "1"})
    if not r.is_success or not r.json():
        raise HTTPException(404, "Strategy not found")
    return r.json()[0]


async def mt5_connected(uid: str, token: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/broker_accounts", headers=headers(token), params={"user_id": f"eq.{uid}", "connector_type": "eq.mt5", "select": "id", "limit": "1"})
    if not r.is_success:
        raise HTTPException(502, "Could not verify your MetaTrader 5 connection")
    return bool(r.json())


async def save(sid: str, uid: str, token: str, state: dict, status: str | None = None):
    payload = {"spec": state, "updated_at": datetime.now(timezone.utc).isoformat()}
    if status:
        payload["status"] = status
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(f"{SUPABASE_URL}/rest/v1/strategies", headers=headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"}, json=payload)
    if not r.is_success:
        raise HTTPException(502, "Could not persist strategy state")


def norm(x: str) -> str:
    return re.sub(r"\s+", " ", x.strip().lower())


def strategy_request(x: str) -> bool:
    v = norm(x)
    keys = ("rsi", "bollinger", "ema", "sma", "macd", "atr", "adx", "stochastic", "moving average", "mean reversion", "breakout", "crossover")
    return any(k in v for k in keys) and any(k in v for k in ("buy", "sell", "enter", "exit", "trade", "strategy"))


def backtest_request(x: str) -> bool:
    return "backtest" in norm(x)


def yes(x: str) -> bool:
    return norm(x) in {"yes", "y", "confirm", "confirmed", "proceed", "go ahead", "do it", "start", "start research", "start it"}


def do_request(x: str) -> bool:
    return norm(x) in {"do", "proceed", "continue", "next", "go", "move on", "do it", "start"}


def connected_confirmation(x: str) -> bool:
    v = norm(x)
    return v in {"connected", "mt5 connected", "i connected mt5", "meta trader connected", "metatrader connected", "done"} or ("connected" in v and "mt5" in v)


def approve(x: str) -> bool:
    return norm(x) in {"approve", "approved", "approve it"}


def paper(x: str) -> bool:
    return "paper trading" in norm(x) or "paper trade" in norm(x)


def live(x: str) -> bool:
    v = norm(x)
    return "live trade" in v or "live trading" in v or "start live" in v


def approval_recorded(state: dict) -> bool:
    if state.get("approved") is True:
        return True
    for item in state.get("activity", []):
        if isinstance(item, dict) and "human approval recorded" in str(item.get("title", "")).lower():
            return True
    return False


def normalize_gate_state(state: dict) -> None:
    """Reconcile older pipeline states with the authoritative dashboard activity.

    Some earlier pipeline writes recorded the approval activity but left
    pipeline_stage at backtest_complete and omitted approved=true. The chat
    must derive the same gate state the dashboard is already showing instead
    of sending the user backwards through completed gates.
    """
    if approval_recorded(state) and state.get("backtest"):
        state["approved"] = True
        if state.get("pipeline_stage") in {"backtest_complete", "approval_complete", "approved", None}:
            state["pipeline_stage"] = "paper_ready"
        agents = dict(state.get("agents", {}))
        agents["approval"] = "complete"
        if state.get("pipeline_stage") in {"paper_ready", "paper_running"}:
            agents["paper"] = "current"
        state["agents"] = agents
        if state.get("pipeline_stage") == "paper_ready":
            state["pending_confirmation"] = "paper_launch"


def activity(state: dict, title: str, detail: str, status: str = "complete") -> None:
    items = list(state.get("activity", []))
    items.append({"time": datetime.now(timezone.utc).isoformat(), "title": title, "detail": detail, "status": status})
    state["activity"] = items[-20:]


@api_router.post("/chat")
async def chat(req: ChatRequest, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    token = user.get("_access_token") or user.get("access_token")
    if not token:
        raise HTTPException(401, "Missing access token")

    strategy = await load(req.strategy_id, user["id"], token)
    state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
    normalize_gate_state(state)
    text = norm(req.message)
    action = response = None

    if strategy_request(req.message):
        if not await mt5_connected(user["id"], token):
            state["pipeline_stage"] = "awaiting_mt5_connection"
            state["pending_confirmation"] = "mt5_connection"
            state["agents"] = {**state.get("agents", {}), "research": "idle", "backtest": "idle", "indicator": "gated", "paper": "gated", "approval": "gated", "live": "gated"}
            state.pop("error", None)
            activity(state, "Waiting for MetaTrader 5", "Connect your MT5 account in Settings → Brokers before research can start.", "blocked")
            action = "connect_mt5"
            response = "I’m ready to work on this strategy. First, connect your MetaTrader 5 account in Settings → Brokers so I can use your account’s market data. Once connected, tell me **MT5 connected** and I’ll ask for confirmation before research starts."
            await save(req.strategy_id, user["id"], token, state, "awaiting_mt5")
        else:
            state["pipeline_stage"] = "awaiting_research_confirmation"
            state["pending_confirmation"] = "research_start"
            state["agents"] = {**state.get("agents", {}), "research": "idle", "backtest": "gated", "indicator": "gated", "paper": "gated", "approval": "gated", "live": "gated"}
            state.pop("error", None)
            action = "confirm_research"
            response = "I’ve understood the strategy and your MetaTrader 5 connection is ready. **Shall I start the Research Agent now?** After research is complete, I’ll tell you that research is done and ask before moving to the deterministic backtest."
            await save(req.strategy_id, user["id"], token, state, "ready")

    elif state.get("pending_confirmation") == "mt5_connection" and (connected_confirmation(text) or yes(text)):
        if not await mt5_connected(user["id"], token):
            action = "connect_mt5"
            response = "I’m not seeing the MetaTrader 5 connection yet. Please connect it in Settings → Brokers, then tell me **MT5 connected**."
            await save(req.strategy_id, user["id"], token, state, "awaiting_mt5")
        else:
            state["pipeline_stage"] = "awaiting_research_confirmation"
            state["pending_confirmation"] = "research_start"
            action = "confirm_research"
            response = "Great — your MetaTrader 5 account is connected. **Shall I start the Research Agent?**"
            await save(req.strategy_id, user["id"], token, state, "ready")

    elif yes(text) and state.get("pending_confirmation") == "research_start":
        if not await mt5_connected(user["id"], token):
            state["pipeline_stage"] = "awaiting_mt5_connection"
            state["pending_confirmation"] = "mt5_connection"
            response = "Before I begin, please connect your MetaTrader 5 account in Settings → Brokers. Then tell me **MT5 connected** and I’ll continue."
            await save(req.strategy_id, user["id"], token, state, "awaiting_mt5")
        else:
            state["pipeline_stage"] = "research_queued"
            state["pending_confirmation"] = None
            state["agents"] = {**state.get("agents", {}), "research": "queued", "backtest": "gated", "indicator": "gated", "paper": "gated", "approval": "gated", "live": "gated"}
            activity(state, "Research Agent queued", "Research will run first; the deterministic backtest remains behind its own confirmation gate.", "running")
            action = "research"
            response = "Confirmed. **Research Agent is starting now.** I’ll tell you when research is complete, show the research findings on the dashboard, and then ask whether to start the deterministic backtest."
            await save(req.strategy_id, user["id"], token, state, "research")
            background_tasks.add_task(run_research, req.strategy_id, user["id"], token)

    elif (backtest_request(text) or yes(text)) and state.get("pending_confirmation") in {"backtest", "backtest_review"}:
        if not await mt5_connected(user["id"], token):
            state["pipeline_stage"] = "awaiting_mt5_connection"
            state["pending_confirmation"] = "mt5_connection"
            response = "Please connect your MetaTrader 5 account in Settings → Brokers before I continue with the backtest."
            await save(req.strategy_id, user["id"], token, state, "awaiting_mt5")
        elif backtest_request(text):
            state["pipeline_stage"] = "awaiting_backtest_confirmation"
            state["pending_confirmation"] = "backtest"
            action = "confirm_backtest"
            response = "Research is done. **Shall I start the deterministic backtest now?**"
            await save(req.strategy_id, user["id"], token, state, "research_complete")
        else:
            state["pipeline_stage"] = "backtest_running"
            state["pending_confirmation"] = None
            state["agents"] = {**state.get("agents", {}), "research": "complete", "backtest": "running", "indicator": "running", "paper": "gated", "approval": "gated", "live": "gated"}
            activity(state, "Deterministic Backtest Agent queued", "Backtest confirmed by the user; running the deterministic historical test now.", "running")
            action = "backtest"
            response = "Confirmed. **Deterministic Backtest Agent is running now.** The dashboard will show the exact criteria, data source, trade count and performance metrics when complete."
            await save(req.strategy_id, user["id"], token, state, "backtesting")
            background_tasks.add_task(run_backtest, req.strategy_id, user["id"], token)

    elif backtest_request(text):
        if state.get("pipeline_stage") == "research_complete":
            state["pending_confirmation"] = "backtest"
            action = "confirm_backtest"
            response = "Research is done. **Shall I start the deterministic backtest now?**"
            await save(req.strategy_id, user["id"], token, state, "research_complete")
        elif not await mt5_connected(user["id"], token):
            state["pipeline_stage"] = "awaiting_mt5_connection"
            state["pending_confirmation"] = "mt5_connection"
            response = "Before I run the backtest, please connect your MetaTrader 5 account in Settings → Brokers. Once connected, tell me **MT5 connected**."
            await save(req.strategy_id, user["id"], token, state, "awaiting_mt5")
        else:
            state["pipeline_stage"] = "awaiting_backtest_confirmation"
            state["pending_confirmation"] = "backtest"
            action = "confirm_backtest"
            response = "The research stage is ready for the next step. **Shall I start the deterministic backtest?**"
            await save(req.strategy_id, user["id"], token, state, "research_complete")

    elif approve(text):
        if approval_recorded(state) and state.get("backtest"):
            state["approved"] = True
            state["pipeline_stage"] = "paper_ready"
            state["pending_confirmation"] = "paper_launch"
            state["agents"] = {**state.get("agents", {}), "approval": "complete", "paper": "current", "live": "gated"}
            action = "already_approved"
            response = "Your strategy is already approved. **Paper trading is ready to start.**"
            await save(req.strategy_id, user["id"], token, state, "paper_ready")
        elif state.get("pipeline_stage") != "backtest_complete" or not state.get("backtest"):
            response = "Approval is available after the deterministic backtest is complete. I’ll show the backtest criteria and results on the dashboard first."
        else:
            state["approved"] = True
            state["approved_at"] = datetime.now(timezone.utc).isoformat()
            state["pipeline_stage"] = "paper_ready"
            state["pending_confirmation"] = "paper_launch"
            state["agents"] = {**state.get("agents", {}), "approval": "complete", "paper": "current", "live": "gated"}
            activity(state, "Human approval recorded", "Backtest passed the review gate and the strategy is now eligible for paper trading.")
            action = "approve"
            response = "Approved. **Paper trading is now ready.** Say **do paper trade** when you want to start the paper session."
            await save(req.strategy_id, user["id"], token, state, "paper_ready")

    elif paper(text) or (do_request(text) and approval_recorded(state) and state.get("backtest") and state.get("pipeline_stage") not in {"paper_complete", "live_ready", "live_running"}):
        normalize_gate_state(state)
        if not state.get("backtest"):
            response = "Paper trading is unavailable because the deterministic backtest has not completed yet."
            action = "paper_gated"
        elif not approval_recorded(state):
            response = "Paper trading is locked until human approval is recorded. The deterministic backtest is complete, so approval is the next step."
            action = "paper_gated"
        else:
            state["approved"] = True
            state["pipeline_stage"] = "paper_ready"
            state["pending_confirmation"] = "paper_launch"
            state["agents"] = {**state.get("agents", {}), "approval": "complete", "paper": "current", "live": "gated"}
            action = "paper_ready"
            response = "**Paper trading is ready.** Your backtest passed and human approval is already recorded. The next action is to start the paper session."
            await save(req.strategy_id, user["id"], token, state, "paper_ready")

    elif live(text):
        normalize_gate_state(state)
        if state.get("pipeline_stage") != "paper_complete":
            action = "live_gated"
            response = "**Live trading is locked for now.** Your strategy must complete paper trading first. Once paper trading passes, ManiQuantAI can move the approved strategy to the MetaTrader 5 live-execution gate."
        else:
            action = "live_ready"
            response = "The strategy has completed paper trading and is eligible for the MetaTrader 5 live-execution gate. Confirm the live execution request to continue."

    if response is not None:
        return JSONResponse({"type": "action", "action": action, "content": response, "pipeline_stage": state.get("pipeline_stage"), "deterministic": True})

    context = f"Strategy: {strategy.get('name')}\nRaw strategy: {strategy.get('raw_strategy_text')}\nPipeline: {state.get('pipeline_stage')}\nAgents: {json.dumps(state.get('agents', {}))}\nResearch: {json.dumps(state.get('research', {}))}\nResearch criteria: {json.dumps(state.get('research_criteria', {}))}\nBacktest: {json.dumps(state.get('backtest', {}))}\nBacktest criteria: {json.dumps(state.get('backtest_criteria', {}))}"
    messages = [{"role": "system", "content": SYSTEM + "\n\n" + context}, {"role": "user", "content": req.message}]

    async def stream():
        try:
            async for event in llm_router.stream_chat(messages=messages, max_tokens=512, temperature=0.1):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        yield 'data: {"type":"done"}\n\n'

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
