"""Explicit paper-trading choice and audited live-trading bypass."""
from __future__ import annotations
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .auth import get_current_user

api_router = APIRouter(prefix="/api", tags=["paper-decision"])
SB = "https://zuimeyynaarjsovnqilk.supabase.co"
ANON = "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X"

class DecisionRequest(BaseModel):
    strategy_id: str
    decision: str  # yes | no | live_yes | live_no

def headers(token: str) -> dict[str, str]:
    return {"apikey": ANON, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}

async def load(sid: str, uid: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SB}/rest/v1/strategies", headers=headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}", "select": "strategy_id,spec,status", "limit": "1"})
    if not r.is_success or not r.json():
        raise HTTPException(404, "Strategy not found")
    return r.json()[0]

async def save(sid: str, uid: str, token: str, state: dict, status: str) -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(f"{SB}/rest/v1/strategies", headers=headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"}, json={"spec": state, "status": status, "updated_at": datetime.now(timezone.utc).isoformat()})
    if not r.is_success:
        raise HTTPException(502, "Could not persist strategy state")

def add_activity(state: dict, title: str, detail: str, status: str = "complete") -> None:
    items = list(state.get("activity", []))
    items.append({"time": datetime.now(timezone.utc).isoformat(), "title": title, "detail": detail, "status": status})
    state["activity"] = items[-20:]

@api_router.post("/paper-decision")
async def paper_decision(req: DecisionRequest, user=Depends(get_current_user)):
    token = user.get("_access_token") or user.get("access_token")
    if not token:
        raise HTTPException(401, "Missing access token")
    strategy = await load(req.strategy_id, user["id"], token)
    state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
    if not state.get("backtest"):
        raise HTTPException(409, "Deterministic backtest must be complete before choosing paper trading.")
    approved = state.get("approved") is True or any(isinstance(x, dict) and "human approval recorded" in str(x.get("title", "")).lower() for x in state.get("activity", []))
    decision = req.decision.strip().lower()

    if decision == "yes":
        state["paper_skipped"] = False
        state["paper_skip_reason"] = None
        state["pipeline_stage"] = "paper_ready"
        state["pending_confirmation"] = None
        state["agents"] = {**state.get("agents", {}), "approval": "complete" if approved else state.get("agents", {}).get("approval", "gated"), "paper": "current", "live": "gated"}
        add_activity(state, "Paper trading selected", "User chose Yes. Paper trading will run before live-trading eligibility.")
        await save(req.strategy_id, user["id"], token, state, "paper_ready")
        return {"ok": True, "next_action": "start_paper", "message": "Yes selected. I’ll start paper trading now. Live trading remains locked until paper trading completes successfully."}

    if decision == "no":
        state["paper_skipped"] = True
        state["paper_skip_reason"] = "explicit_user_decline"
        state["pipeline_stage"] = "awaiting_live_approval"
        state["pending_confirmation"] = "live_approval"
        state["agents"] = {**state.get("agents", {}), "approval": "complete" if approved else "gated", "paper": "skipped", "live": "gated"}
        add_activity(state, "Paper trading declined", "User explicitly chose not to run paper trading. Live trading now requires a separate explicit human approval.", "complete")
        await save(req.strategy_id, user["id"], token, state, "awaiting_live_approval")
        return {"ok": True, "next_action": "request_live_approval", "message": "Paper trading will be skipped. Before any live execution, do you explicitly approve live trading?"}

    if decision == "live_no":
        if state.get("pipeline_stage") != "awaiting_live_approval":
            raise HTTPException(409, "Live approval is not currently requested.")
        state["pending_confirmation"] = "live_approval"
        add_activity(state, "Live trading declined", "User did not approve live execution.", "blocked")
        await save(req.strategy_id, user["id"], token, state, "awaiting_live_approval")
        return {"ok": True, "next_action": "request_live_approval", "message": "Live trading remains locked. No live order was submitted."}

    if decision == "live_yes":
        if state.get("pipeline_stage") != "awaiting_live_approval" or state.get("paper_skipped") is not True:
            raise HTTPException(409, "Live bypass approval is not currently available.")
        state["live_bypass_approved"] = True
        state["paper_complete"] = True
        state["pipeline_stage"] = "live_ready"
        state["pending_confirmation"] = None
        state["approved"] = True
        state["approved_at"] = state.get("approved_at") or datetime.now(timezone.utc).isoformat()
        state["agents"] = {**state.get("agents", {}), "approval": "complete", "paper": "skipped", "live": "current"}
        add_activity(state, "Live trading approved", "User explicitly approved live execution after declining paper trading; audited bypass recorded.")
        await save(req.strategy_id, user["id"], token, state, "live_ready")
        return {"ok": True, "next_action": "start_live", "message": "Live trading approved. I’ll proceed to the live-execution gate now."}

    raise HTTPException(400, "Decision must be yes, no, live_yes, or live_no.")
