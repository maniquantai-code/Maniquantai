"""Gated deterministic strategy pipeline with LLM strategy compilation."""
from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from .auth import get_current_user
from .pipeline_mt5 import load, save, parse, bt, yahoo, mt5, _activity
from .broker_accounts import fetch_broker_api_candles
from ..core.strategy_compiler import compile_strategy
api_router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
SB = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
ANON = os.getenv("SUPABASE_ANON_KEY", "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X").strip()
BRIDGE_ONLINE_SECONDS = 15

def _h(token: str): return {"apikey": ANON, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}
async def _accounts(uid: str, token: str):
    async with httpx.AsyncClient(timeout=10) as c: r = await c.get(f"{SB}/rest/v1/broker_accounts", headers=_h(token), params={"user_id": f"eq.{uid}", "select": "id,connector_type,connector_name,label,encrypted_payload,is_primary,bridge_enabled,last_verified_at,created_at", "order": "is_primary.desc,created_at.desc"})
    if not r.is_success: raise RuntimeError("Could not read trading account connections")
    return r.json()
def _mt5_online(account: dict) -> bool:
    if not account.get("bridge_enabled") or not account.get("last_verified_at"): return False
    try:
        ts = datetime.fromisoformat(str(account["last_verified_at"]).replace("Z", "+00:00")); ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ts <= timedelta(seconds=BRIDGE_ONLINE_SECONDS)
    except Exception: return False
async def _market_data(uid: str, sid: str, token: str, spec: dict):
    accounts = await _accounts(uid, token); primary = next((a for a in accounts if a.get("is_primary")), None); ordered = ([primary] + [a for a in accounts if a.get("id") != primary.get("id")]) if primary else accounts; errors=[]
    for account in ordered:
        try:
            if account["connector_type"] == "mt5":
                if not _mt5_online(account): errors.append("MetaTrader 5 bridge is offline"); continue
                rows = await mt5(uid, sid, spec)
            elif account["connector_type"] == "broker_api": rows = await fetch_broker_api_candles(account, spec["symbol"], spec["timeframe"], spec["lookback_days"])
            else: continue
            return rows, account.get("connector_name") or "Broker API"
        except Exception as exc: errors.append(f"{account.get('connector_name', 'Broker')}: {str(exc)[:180]}")
    try: return await yahoo(spec["symbol"], spec["timeframe"], spec["lookback_days"]), "Yahoo Finance"
    except Exception as exc: raise RuntimeError("No market-data source is available. " + "; ".join(errors + [f"Yahoo Finance: {str(exc)[:180]}"]))
def _runtime_from_compiled(compiled: dict) -> dict:
    runtime = compiled.get("runtime") or {}; required=("symbol","timeframe","lookback_days","rsi_period","rsi_entry_below","rsi_exit_above","bollinger_period","bollinger_std","risk_pct","max_hold_hours","stop_loss","take_profit"); missing=[k for k in required if k not in runtime]
    if missing: raise RuntimeError("Strategy compiler returned an incomplete runtime: " + ", ".join(missing))
    if runtime.get("symbol") == "unresolved" or runtime.get("timeframe") == "unresolved": raise RuntimeError("Strategy compiler could not resolve the instrument or timeframe")
    return runtime
async def _compile_and_store(strategy_id: str, user_id: str, token: str, strategy: dict, state: dict) -> dict:
    compiled = await compile_strategy(strategy.get("raw_strategy_text") or ""); runtime = _runtime_from_compiled(compiled); state["strategy_spec"]=compiled; state["parsed_strategy"]=runtime; state["compiler"]=compiled.get("compiler", {}); state["unresolved"]=compiled.get("unresolved", []); state["strategy_compiled_at"]=datetime.now(timezone.utc).isoformat(); return runtime
async def run_research(strategy_id: str, user_id: str, token: str):
    try:
        strategy=await load(strategy_id,user_id,token); state=strategy.get("spec") or {}; spec=state.get("parsed_strategy") or await _compile_and_store(strategy_id,user_id,token,strategy,state); state["pipeline_stage"]="research_running"; state["pending_confirmation"]=None; state["agents"]={**state.get("agents",{}),"research":"running","backtest":"queued","indicator":"gated","paper":"gated","approval":"gated","live":"gated"}; _activity(state,"Research Agent started",f"Analysing {spec['symbol']} on {spec['timeframe']} using the selected market-data connector.","running"); await save(strategy_id,user_id,token,state,"research"); rows,source=await _market_data(user_id,strategy_id,token,spec); minimum=max(int(spec["rsi_period"]),int(spec["bollinger_period"]))+5
        if len(rows)<minimum: raise RuntimeError("Not enough market data for the requested indicators")
        state["data_source"]=source; state["data_source_message"]=f"Market data source: {source}."; state["bars_loaded"]=len(rows); state["research"]={"status":"complete","bars_checked":len(rows),"data_source":source}; state["pipeline_stage"]="research_complete"; state["pending_confirmation"]="backtest"; state["agents"]={**state.get("agents",{}),"research":"complete","backtest":"gated","indicator":"gated","paper":"gated","approval":"gated","live":"gated"}; _activity(state,"Research Agent complete",f"Verified {len(rows):,} bars from {source}. Deterministic backtest is ready for confirmation."); await save(strategy_id,user_id,token,state,"research_complete")
    except Exception as exc:
        state=(await load(strategy_id,user_id,token)).get("spec") or {}; state["pipeline_stage"]="research_failed"; state["error"]=str(exc); state["agents"]={**state.get("agents",{}),"research":"failed","backtest":"gated"}; _activity(state,"Research Agent failed",str(exc)[:240],"failed"); await save(strategy_id,user_id,token,state,"research_failed")
async def run_backtest(strategy_id: str, user_id: str, token: str):
    try:
        strategy=await load(strategy_id,user_id,token); state=strategy.get("spec") or {}; spec=state.get("parsed_strategy") or await _compile_and_store(strategy_id,user_id,token,strategy,state); state["pipeline_stage"]="backtest_running"; state["pending_confirmation"]=None; state["agents"]={**state.get("agents",{}),"research":"complete","backtest":"running","indicator":"running","paper":"gated","approval":"gated","live":"gated"}; _activity(state,"Deterministic Backtest Agent started",f"Testing {spec['symbol']} with deterministic rules; the LLM is not used to calculate performance.","running"); await save(strategy_id,user_id,token,state,"backtesting"); rows,source=await _market_data(user_id,strategy_id,token,spec); result=bt(rows,spec); state["data_source"]=source; state["bars_loaded"]=len(rows); state["backtest"]={**result,"symbol":spec["symbol"],"timeframe":spec["timeframe"],"period_days":spec["lookback_days"],"data_source":source}; state["pipeline_stage"]="backtest_complete"; state["pending_confirmation"]="approval"; state["agents"]={**state.get("agents",{}),"research":"complete","backtest":"complete","indicator":"complete","paper":"gated","approval":"current","live":"gated"}; m=result["metrics"]; _activity(state,"Deterministic Backtest complete",f"{m['trade_count']} trades · {m['win_rate']}% win rate · {m['total_return_pct']}% return · {m['max_drawdown_pct']}% max drawdown."); await save(strategy_id,user_id,token,state,"backtest_complete")
    except Exception as exc:
        state=(await load(strategy_id,user_id,token)).get("spec") or {}; state["pipeline_stage"]="backtest_failed"; state["error"]=str(exc); state["agents"]={**state.get("agents",{}),"backtest":"failed"}; _activity(state,"Deterministic Backtest failed",str(exc)[:240],"failed"); await save(strategy_id,user_id,token,state,"backtest_failed")
async def run_pipeline(strategy_id,user_id,token): await run_research(strategy_id,user_id,token)
@api_router.post("/{strategy_id}/start")
async def start(strategy_id: str, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    token=user.get("_access_token") or user.get("access_token")
    if not token: raise HTTPException(401,"Missing access token")
    strategy=await load(strategy_id,user["id"],token); state=strategy.get("spec") or {}
    try:
        if not state.get("strategy_spec"): await _compile_and_store(strategy_id,user["id"],token,strategy,state)
        state["pipeline_stage"]="awaiting_research_confirmation"; state["pending_confirmation"]="research_start"; state["agents"]={"research":"gated","backtest":"gated","indicator":"gated","paper":"gated","approval":"gated","live":"gated"}; _activity(state,"Strategy compiled","The user prompt was converted into a deterministic strategy specification. Research is waiting for user confirmation."); await save(strategy_id,user["id"],token,state,"ready")
        return {"action":"confirm_research","pipeline_stage":state["pipeline_stage"],"content":"Your strategy has been compiled into a deterministic specification. **Shall I start the Research Agent?**"}
    except Exception as exc:
        state["pipeline_stage"]="strategy_compilation_failed"; state["pending_confirmation"]=None; state["error"]=str(exc); await save(strategy_id,user["id"],token,state,"failed"); raise HTTPException(422,f"Strategy compilation failed: {str(exc)[:300]}")
@api_router.post("/{strategy_id}/research/confirm")
async def confirm_research(strategy_id: str, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    token=user.get("_access_token") or user.get("access_token")
    if not token: raise HTTPException(401,"Missing access token")
    strategy=await load(strategy_id,user["id"],token); state=strategy.get("spec") or {}
    if state.get("pending_confirmation")!="research_start": raise HTTPException(409,"Research is not waiting for confirmation")
    state["pending_confirmation"]=None; await save(strategy_id,user["id"],token,state,"research"); background_tasks.add_task(run_research,strategy_id,user["id"],token); return {"action":"research","content":"Confirmed. **Research Agent is starting now.**"}
@api_router.get("/status/{strategy_id}")
async def status(strategy_id:str,user=Depends(get_current_user)):
    token=user.get("_access_token") or user.get("access_token")
    if not token: raise HTTPException(401,"Missing access token")
    strategy=await load(strategy_id,user["id"],token); state=strategy.get("spec") or {}
    return {"strategy_id":strategy_id,"status":strategy.get("status"),"pipeline_stage":state.get("pipeline_stage"),"pending_confirmation":state.get("pending_confirmation"),"agents":state.get("agents",{}),"activity":state.get("activity",[]),"research":state.get("research"),"backtest":state.get("backtest"),"strategy_spec":state.get("strategy_spec"),"data_source":state.get("data_source"),"bars_loaded":state.get("bars_loaded"),"error":state.get("error")}
