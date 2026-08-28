"""Explicit paper-trading choice and audited live-trading gate."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .auth import get_current_user

api_router = APIRouter(prefix="/api", tags=["paper-decision"])
SB = "https://zuimeyynaarjsovnqilk.supabase.co"
ANON = "sb_publishable_Uf0ECWKkKrH6pzedVbTOA_aNlp1J1X"
BRIDGE_ONLINE_SECONDS = 15

class DecisionRequest(BaseModel):
    strategy_id: str
    decision: str

def headers(token: str) -> dict[str, str]:
    return {"apikey": ANON, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}

async def load(sid: str, uid: str, token: str) -> dict:
    sid = sid.strip()
    if not sid: raise HTTPException(400, "Missing strategy id")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SB}/rest/v1/strategies", headers=headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}", "select": "strategy_id,user_id,spec,status", "limit": "1"})
        if r.is_success and r.json():
            row=r.json()[0]
            if row.get("user_id")==uid: return row
        r2=await c.get(f"{SB}/rest/v1/strategies", headers=headers(token), params={"strategy_id": f"eq.{sid}", "select": "strategy_id,user_id,spec,status", "limit": "1"})
    if r2.is_success and r2.json():
        row=r2.json()[0]
        if row.get("user_id")==uid: return row
    raise HTTPException(404, "Strategy not found for the authenticated user")

async def save(sid: str, uid: str, token: str, state: dict, status: str) -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.patch(f"{SB}/rest/v1/strategies", headers=headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"}, json={"spec":state,"status":status,"updated_at":datetime.now(timezone.utc).isoformat()})
    if not r.is_success: raise HTTPException(502,"Could not persist strategy state")
    if not r.json(): raise HTTPException(409,"Strategy could not be updated for the authenticated user")

def add_activity(state: dict, title: str, detail: str, status: str="complete") -> None:
    items=list(state.get("activity",[])); items.append({"time":datetime.now(timezone.utc).isoformat(),"title":title,"detail":detail,"status":status}); state["activity"]=items[-20:]

async def bridge_online(uid: str, token: str) -> bool:
    cutoff=(datetime.now(timezone.utc)-timedelta(seconds=BRIDGE_ONLINE_SECONDS)).isoformat()
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.get(f"{SB}/rest/v1/broker_accounts",headers=headers(token),params={"user_id":f"eq.{uid}","connector_type":"eq.mt5","bridge_enabled":"eq.true","last_verified_at":f"gte.{cutoff}","select":"id","limit":"1"})
    if not r.is_success: raise HTTPException(502,"Could not verify the MetaTrader 5 bridge")
    return bool(r.json())

@api_router.post("/paper-decision")
async def paper_decision(req: DecisionRequest,user=Depends(get_current_user)):
    token=user.get("_access_token") or user.get("access_token")
    if not token: raise HTTPException(401,"Missing access token")
    strategy=await load(req.strategy_id,user["id"],token); state=strategy.get("spec") if isinstance(strategy.get("spec"),dict) else {}
    if not state.get("backtest"): raise HTTPException(409,"Deterministic backtest must be complete before choosing paper trading.")
    approved=state.get("approved") is True or any(isinstance(x,dict) and "human approval recorded" in str(x.get("title","")).lower() for x in state.get("activity",[]))
    decision=req.decision.strip().lower()

    if decision=="yes":
        state["paper_skipped"]=False; state["paper_skip_reason"]=None; state["pipeline_stage"]="paper_ready"; state["pending_confirmation"]=None
        state["agents"]={**state.get("agents",{}),"approval":"complete" if approved else state.get("agents",{}).get("approval","gated"),"paper":"current","live":"gated"}
        add_activity(state,"Paper trading selected","User chose Yes. Paper trading will run before live-trading eligibility.")
        await save(req.strategy_id,user["id"],token,state,"paper_ready")
        return {"ok":True,"next_action":"start_paper","message":"Yes selected. I’ll start paper trading now. Live trading remains locked until paper trading completes successfully."}

    if decision=="no":
        state["paper_skipped"]=True; state["paper_skip_reason"]="explicit_user_decline"; state["pipeline_stage"]="awaiting_live_approval"; state["pending_confirmation"]="live_approval"
        state["agents"]={**state.get("agents",{}),"approval":"complete" if approved else "gated","paper":"skipped","live":"gated"}
        add_activity(state,"Paper trading declined","User explicitly chose not to run paper trading. Live trading now requires a separate explicit human approval.")
        await save(req.strategy_id,user["id"],token,state,"awaiting_live_approval")
        return {"ok":True,"next_action":"request_live_approval","message":"Paper trading will be skipped. Before any live execution, do you explicitly approve live trading?"}

    if decision=="live_no":
        if state.get("pipeline_stage") not in {"awaiting_live_approval","live_ready","live_running"}: raise HTTPException(409,"Live approval is not currently requested.")
        state["pending_confirmation"]="live_approval"; state["live_approved"]=False; state["live_bypass_approved"]=False; state["pipeline_stage"]="awaiting_live_approval"
        add_activity(state,"Live trading declined","User did not approve live execution.","blocked")
        await save(req.strategy_id,user["id"],token,state,"awaiting_live_approval")
        return {"ok":True,"next_action":"request_live_approval","message":"Live trading remains locked. No live order was submitted."}

    if decision=="live_yes":
        stage=state.get("pipeline_stage"); paper_skipped=state.get("paper_skipped") is True
        paper_complete=state.get("paper_complete") is True or state.get("paper",{}).get("complete") is True or state.get("paper_status") in {"complete","completed","passed"}
        if stage=="awaiting_live_approval" and not paper_skipped and not paper_complete: raise HTTPException(409,"Paper trading must complete before live approval, or be explicitly declined first.")
        if stage not in {"awaiting_live_approval","live_ready","live_running"}: raise HTTPException(409,"Live approval is not currently available. Complete the required trading gates first.")
        bypass=paper_skipped
        state["live_bypass_approved"]=bypass; state["paper_complete"]=True if (paper_complete or bypass) else state.get("paper_complete",False)
        state["pending_confirmation"]=None; state["approved"]=True; state["live_approved"]=True
        state["approved_at"]=state.get("approved_at") or datetime.now(timezone.utc).isoformat()
        # Approval immediately arms the autonomous live agent. There is no
        # second Start Live click. The MT5 bridge agent will begin scanning as
        # soon as its heartbeat is online, while the database status remains
        # live_approved so the bridge authorization function accepts signals.
        state["pipeline_stage"]="live_running"
        state["agents"]={**state.get("agents",{}),"approval":"complete","paper":"skipped" if bypass else "complete","live":"current"}
        bridge=await bridge_online(user["id"],token)
        detail=("User explicitly approved live execution after declining paper trading; audited bypass recorded. Autonomous MT5 market scanning is armed." if bypass else "User explicitly approved live execution after the required paper-trading gate completed. Autonomous MT5 market scanning is armed.")
        if not bridge: detail += " The MT5 bridge is currently offline; scanning will begin automatically when the bridge heartbeat returns."
        else: detail += " The MT5 bridge is online; the live scanner can begin immediately."
        add_activity(state,"Live trading approved",detail)
        await save(req.strategy_id,user["id"],token,state,"live_approved")
        return {"ok":True,"next_action":"live_running","bridge_online":bridge,"message":"Live trading approved. The live agent is armed and will automatically scan MetaTrader 5 market data and execute only when the approved strategy conditions are met. No order was submitted by the approval action."}

    if decision=="live_start":
        if state.get("pipeline_stage") not in {"live_ready","live_running"} or state.get("live_approved") is not True: raise HTTPException(409,"Live trading is not ready. Complete the required gates and explicit live approval first.")
        if not await bridge_online(user["id"],token):
            add_activity(state,"Live execution waiting","MetaTrader 5 bridge is offline. The approved live agent will resume automatically when the bridge heartbeat returns.","blocked")
            await save(req.strategy_id,user["id"],token,state,"live_approved")
            raise HTTPException(409,"MetaTrader 5 bridge is offline. Keep the MT5 terminal and ManiQuantAI bridge running; live scanning will resume automatically.")
        state["pipeline_stage"]="live_running"; state["pending_confirmation"]=None; state["agents"]={**state.get("agents",{}),"approval":"complete","paper":"skipped" if state.get("paper_skipped") else "complete","live":"current"}
        add_activity(state,"Live execution confirmed","MetaTrader 5 bridge is online. Autonomous live scanning is active.","running")
        await save(req.strategy_id,user["id"],token,state,"live_approved")
        return {"ok":True,"next_action":"live_running","message":"Autonomous live execution is active. MetaTrader 5 is connected and the approved strategy is being scanned continuously."}

    raise HTTPException(400,"Decision must be yes, no, live_yes, live_no, or live_start.")
