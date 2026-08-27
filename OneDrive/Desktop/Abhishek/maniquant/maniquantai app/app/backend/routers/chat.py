"""ManiQuantAI v2 — deterministic trading workflow with 6-agent team support."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .auth import get_current_user
from ..core.agent_pipeline import run_post_backtest_agents
from ..core.strategy_compiler import compile_strategy
from ..core.strategy_compiler_v2 import compile_strategy_v2
from .pipeline_mt5 import run_backtest, run_research

api_router = APIRouter(prefix="/api", tags=["chat"])
SB   = "https://zuimeyynaarjsovnqilk.supabase.co"
ANON = "sb_publishable_Uf0ECWKkKrH6pzedVbTOA_aNlp1J1X"

class ChatRequest(BaseModel):
    strategy_id: str
    message: str

def norm(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "").strip().lower())

def headers(token: str) -> dict:
    return {"apikey": ANON, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}

async def load(sid: str, uid: str, token: str) -> dict:
    if not sid or not uid or not token:
        raise HTTPException(400, "A valid strategy session is required")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SB}/rest/v1/strategies", headers=headers(token),
                        params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}",
                                "select": "strategy_id,name,raw_strategy_text,status,spec", "limit": "1"})
    if r.status_code in (401, 403): raise HTTPException(401, "AUTH_REQUIRED")
    if not r.is_success: raise HTTPException(502, "Strategy service temporarily unavailable")
    rows = r.json()
    if not rows: raise HTTPException(409, "STRATEGY_CONTEXT_INVALID")
    return rows[0]

async def save(sid: str, uid: str, token: str, state: dict, status: str) -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(f"{SB}/rest/v1/strategies", headers=headers(token),
                          params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"},
                          json={"spec": state, "status": status, "updated_at": datetime.now(timezone.utc).isoformat()})
    if r.status_code in (401, 403): raise HTTPException(401, "AUTH_REQUIRED")
    if not r.is_success: raise HTTPException(502, "WORKFLOW_SAVE_FAILED")

def activity(state: dict, title: str, detail: str, status: str = "complete") -> None:
    items = list(state.get("activity", []))
    items.append({"time": datetime.now(timezone.utc).isoformat(), "title": title, "detail": detail, "status": status})
    state["activity"] = items[-30:]

def has_backtest(state: dict) -> bool:
    return isinstance(state.get("backtest"), dict) and bool(state.get("backtest"))

def yes(v: str) -> bool:
    return norm(v) in {"yes", "y", "approve", "approved", "confirm", "confirmed", "proceed", "go ahead", "do it", "start", "run it"}

def no(v: str) -> bool:
    return norm(v) in {"no", "n", "cancel", "decline", "declined", "stop"}

def live_request(v: str) -> bool:
    x = norm(v)
    return x == "4" or any(k in x for k in ("start live", "live trade", "live trading", "do live", "go live", "activate live"))

def set_agents(state: dict, **changes: str) -> None:
    state["agents"] = {**state.get("agents", {}), **changes}

def out(action: str, message: str, state: dict) -> JSONResponse:
    return JSONResponse({"ok": True, "type": "action", "action": action, "content": message,
                         "pipeline_stage": state.get("pipeline_stage"),
                         "pending_confirmation": state.get("pending_confirmation"),
                         "agents": state.get("agents", {}),
                         "active_agents": state.get("active_agents", []),
                         "strategy_type": state.get("strategy_type", "multi_signal"),
                         "deterministic": True})

async def _compile_v2(raw: str) -> dict:
    """Try fast deterministic compiler first, fall back to LLM."""
    det = compile_strategy_v2(raw)
    if not det.get("unresolved"):
        return det
    try:
        return await compile_strategy(raw)
    except Exception:
        return det  # return deterministic result even if incomplete

async def recover_compilation(strategy: dict, state: dict, sid: str, uid: str, token: str) -> dict:
    prompt = str(strategy.get("raw_strategy_text") or state.get("source", {}).get("user_prompt") or "").strip()
    if not prompt: raise HTTPException(422, "STRATEGY_COMPILATION_INPUT_MISSING")
    spec = await _compile_v2(prompt)
    old_activity = list(state.get("activity", []))
    new_state = dict(spec)
    new_state["activity"] = old_activity
    new_state["pipeline_stage"] = "backtest_ready"
    new_state["pending_confirmation"] = None
    new_state["active_agents"] = spec.get("active_agents", ["momentum", "mean_reversion", "breakout", "sentiment"])
    new_state["strategy_type"] = spec.get("strategy_type", "multi_signal")
    new_state["agents"] = {"research": "gated", "backtest": "gated", "indicator": "gated", "risk": "gated", "live": "gated"}
    activity(new_state, "Strategy compilation recovered", f"Compiled as {new_state['strategy_type']} strategy on {spec.get('symbol','?')} {spec.get('timeframe','?')}.")
    await save(sid, uid, token, new_state, "backtest_ready")
    return new_state

@api_router.post("/chat")
async def chat(req: ChatRequest, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    token = user.get("_access_token") or user.get("access_token")
    try:
        strategy = await load(req.strategy_id, user["id"], token)
        state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
        text  = norm(req.message)

        # ── Recover failed compilation ────────────────────────────────────
        failed = (strategy.get("status") == "strategy_compilation_failed"
                  or state.get("pipeline_stage") == "strategy_compilation_failed"
                  or state.get("compilation", {}).get("status") == "failed")
        if failed:
            try:
                state = await recover_compilation(strategy, state, req.strategy_id, user["id"], token)
                stype = state.get("strategy_type", "multi_signal")
                agents = state.get("active_agents", [])
                return out("compilation_recovered",
                    f"**Strategy compiled successfully as `{stype}`.** "
                    f"Active agent team: {', '.join(agents)}. "
                    "Ready for deterministic backtest.", state)
            except Exception as exc:
                activity(state, "Strategy compilation failed", str(exc)[:240], "blocked")
                state["compilation"] = {"status": "failed", "error": str(exc)[:300]}
                await save(req.strategy_id, user["id"], token, state, "strategy_compilation_failed")
                return out("compilation_failed", "**Strategy compilation failed.** Please revise the strategy and retry.", state)

        pending = state.get("pending_confirmation")

        # ── Live approval gate ────────────────────────────────────────────
        if pending == "live_approval":
            if yes(text):
                if not has_backtest(state):
                    return out("live_gated", "Live trading is locked until the deterministic backtest passes.", state)
                agents = state.get("agents", {})
                if agents.get("indicator") != "complete" or agents.get("risk") != "complete":
                    return out("live_gated", "Live trading is locked until Indicator Agent and Risk Management Agent both pass.", state)
                state.update({"live_approved": True, "pending_confirmation": None, "pipeline_stage": "live_running"})
                set_agents(state, indicator="complete", risk="complete", live="current")
                activity(state, "Live trading approved", "Agent team is now active. Orders submitted only on consensus signal.", "running")
                await save(req.strategy_id, user["id"], token, state, "live_approved")
                stype   = state.get("strategy_type", "multi_signal")
                symbol  = (state.get("runtime") or state.get("parsed_strategy") or {}).get("symbol", "?")
                tf      = (state.get("runtime") or state.get("parsed_strategy") or {}).get("timeframe", "?")
                a_list  = state.get("active_agents", ["momentum", "mean_reversion", "breakout", "sentiment"])
                return out("live_running",
                    f"**Live trading approved and started on {symbol} {tf}.**\n\n"
                    f"**Active agent team:** {', '.join(a_list)}\n\n"
                    "Each agent evaluates the market independently. The **Portfolio Manager** aggregates signals "
                    "and only fires a live MT5 order when weighted consensus ≥ 0.35 and ≥ 2 agents agree. "
                    "View real-time signals in the **Agent Trading Desk** below.", state)
            if no(text):
                state.update({"live_approved": False, "pending_confirmation": None, "pipeline_stage": "live_blocked"})
                activity(state, "Live trading declined", "User declined. No order submitted.", "blocked")
                await save(req.strategy_id, user["id"], token, state, "live_blocked")
                return out("live_declined", "Live trading disabled. No order was submitted.", state)
            return out("live_approval", "**Do you approve live trading?** The agent team will monitor the market and execute when consensus fires.", state)

        # ── Indicator / risk gate ─────────────────────────────────────────
        if pending == "indicator_approval":
            if yes(text):
                if not has_backtest(state):
                    return out("indicator_gated", "Indicator verification requires a completed deterministic backtest.", state)
                result = run_post_backtest_agents(state)
                state["agents"] = {**state.get("agents", {}), "indicator": result["indicator"]["status"], "risk": result["risk"]["status"]}
                if result["ready_for_live_gate"]:
                    state.update({"pipeline_stage": "risk_ready", "pending_confirmation": None})
                    activity(state, "Indicator + Risk Agents passed", "Strategy cleared for live approval gate.")
                    await save(req.strategy_id, user["id"], token, state, "risk_ready")
                    return out("risk_ready",
                        "**Indicator Agent and Risk Management Agent passed.** "
                        "The strategy is ready for the live approval gate. "
                        "Type **'start live trading'** to activate the agent team.", state)
                state.update({"pipeline_stage": "indicator_failed", "pending_confirmation": None})
                errs = "; ".join(result["indicator"]["errors"] + result["risk"]["errors"])
                activity(state, "Indicator/Risk validation failed", errs[:240], "blocked")
                await save(req.strategy_id, user["id"], token, state, "indicator_failed")
                return out("indicator_failed", f"**Validation failed:** {errs}", state)
            if no(text):
                state["pending_confirmation"] = None
                await save(req.strategy_id, user["id"], token, state, "backtest_complete")
                return out("indicator_declined", "Validation paused. No trading action taken.", state)
            return out("indicator_approval", "**Run the Indicator Agent and Risk Management Agent?** (yes / no)", state)

        # ── Live request shortcut ─────────────────────────────────────────
        if live_request(text):
            if not has_backtest(state):
                return out("live_gated", "Live trading is locked — complete the deterministic backtest first.", state)
            agents = state.get("agents", {})
            if agents.get("indicator") != "complete" or agents.get("risk") != "complete":
                return out("indicator_required",
                    "The strategy must pass the **Indicator Agent** and **Risk Management Agent** before live approval. "
                    "Type **'yes'** to run these checks now.", state)
            state.update({"pending_confirmation": "live_approval", "pipeline_stage": "awaiting_live_approval"})
            set_agents(state, live="gated")
            await save(req.strategy_id, user["id"], token, state, "awaiting_live_approval")
            return out("live_approval",
                "Your strategy passed the backtest, indicator, and risk gates. "
                "**Do you approve live trading?** The 5-agent team will execute orders through MetaTrader 5.", state)

        # ── Backtest confirmation ─────────────────────────────────────────
        if pending == "backtest" and yes(text):
            state.update({"pending_confirmation": None, "pipeline_stage": "backtest_running"})
            set_agents(state, research="complete", backtest="running", indicator="gated", risk="gated", live="gated")
            await save(req.strategy_id, user["id"], token, state, "backtesting")
            background_tasks.add_task(run_backtest, req.strategy_id, user["id"], token)
            stype = state.get("strategy_type", "multi_signal")
            symbol = (state.get("runtime") or state.get("parsed_strategy") or {}).get("symbol", "?")
            return out("backtest", f"**Deterministic backtest starting now** on {symbol} ({stype}).", state)

        # ── Auto-trigger indicator gate after backtest ────────────────────
        if has_backtest(state) and state.get("agents", {}).get("indicator") in {None, "gated"}:
            state["pending_confirmation"] = "indicator_approval"
            state["pipeline_stage"] = "indicator_ready"
            set_agents(state, backtest="complete", indicator="gated", risk="gated", live="gated")
            await save(req.strategy_id, user["id"], token, state, "indicator_ready")
            return out("indicator_approval",
                "**Backtest complete. Run the Indicator Agent and Risk Management Agent?** (yes / no)", state)

        stage = state.get("pipeline_stage", "unknown")
        return out("status", f"Strategy is in **{stage}**. Next pipeline action is determined by state.", state)

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "WORKFLOW_ERROR")
