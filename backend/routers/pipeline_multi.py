"""Market-data routed strategy pipeline.

Priority: the user's selected primary connector (MT5 or another broker API),
then Yahoo Finance only if the primary connector fails or no connector exists.
The deterministic backtest and existing gates remain unchanged.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, HTTPException
from .auth import get_current_user
from .pipeline_mt5 import load, save, parse, bt, yahoo, mt5, _activity
from .broker_accounts import fetch_broker_api_candles

api_router=APIRouter(prefix="/api/pipeline",tags=["pipeline"])
SB=os.getenv("SUPABASE_URL","https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
ANON=os.getenv("SUPABASE_ANON_KEY","sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X").strip()

def _h(token): return {"apikey":ANON,"Authorization":f"Bearer {token}","Content-Type":"application/json","Prefer":"return=representation"}

async def _accounts(uid,token):
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.get(f"{SB}/rest/v1/broker_accounts",headers=_h(token),params={"user_id":f"eq.{uid}","select":"id,connector_type,connector_name,label,encrypted_payload,is_primary,created_at","order":"is_primary.desc,created_at.desc"})
    if not r.is_success: raise RuntimeError("Could not read trading account connections")
    return r.json()

async def _market_data(uid,sid,token,spec):
    accounts=await _accounts(uid,token)
    primary=next((a for a in accounts if a.get("is_primary")), None)
    ordered=([primary]+[a for a in accounts if a.get("id")!=primary.get("id")]) if primary else accounts
    errors=[]
    for account in ordered:
        try:
            if account["connector_type"]=="mt5": rows=await mt5(uid,sid,spec)
            elif account["connector_type"]=="broker_api": rows=await fetch_broker_api_candles(account,spec["symbol"],spec["timeframe"],spec["lookback_days"])
            else: continue
            return rows,account["connector_name"] or "Broker API"
        except Exception as exc:
            errors.append(f"{account.get('connector_name','Broker')}: {str(exc)[:180]}")
    try:
        rows=await yahoo(spec["symbol"],spec["timeframe"],spec["lookback_days"])
        return rows,"Yahoo Finance"
    except Exception as exc:
        detail="; ".join(errors+[f"Yahoo Finance: {str(exc)[:180]}"])
        raise RuntimeError(f"No market-data source is available. {detail}")

async def run_research(strategy_id,user_id,token):
    try:
        strategy=await load(strategy_id,user_id,token); state=strategy.get("spec") or {}; spec=parse(strategy.get("raw_strategy_text") or "")
        state["parsed_strategy"]=spec; state["pipeline_stage"]="research_running"; state["pending_confirmation"]=None
        state["agents"]={**state.get("agents",{}),"research":"running","backtest":"queued","indicator":"gated","paper":"gated","approval":"gated","live":"gated"}
        _activity(state,"Research Agent started",f"Analysing {spec['symbol']} on {spec['timeframe']} using the selected market-data connector.","running"); await save(strategy_id,user_id,token,state,"research")
        rows,source=await _market_data(user_id,strategy_id,token,spec)
        minimum=max(spec["rsi_period"],spec["bollinger_period"])+5
        if len(rows)<minimum: raise RuntimeError("Not enough market data for the requested indicators")
        state["data_source"]=source; state["data_source_message"]=f"Market data source: {source}."; state["bars_loaded"]=len(rows)
        state["research"]={"status":"complete","bars_checked":len(rows),"data_source":source}
        state["pipeline_stage"]="research_complete"; state["pending_confirmation"]="backtest"; state["agents"]={**state.get("agents",{}),"research":"complete","backtest":"gated","indicator":"gated","paper":"gated","approval":"gated","live":"gated"}
        _activity(state,"Research Agent complete",f"Verified {len(rows):,} bars from {source}. Deterministic backtest is ready for confirmation."); await save(strategy_id,user_id,token,state,"research_complete")
    except Exception as exc:
        state=(await load(strategy_id,user_id,token)).get("spec") or {}; state["pipeline_stage"]="research_failed"; state["error"]=str(exc); state["agents"]={**state.get("agents",{}),"research":"failed","backtest":"gated"}; _activity(state,"Research Agent failed",str(exc)[:240],"failed"); await save(strategy_id,user_id,token,state,"research_failed")

async def run_backtest(strategy_id,user_id,token):
    try:
        strategy=await load(strategy_id,user_id,token); state=strategy.get("spec") or {}; spec=state.get("parsed_strategy") or parse(strategy.get("raw_strategy_text") or "")
        state["pipeline_stage"]="backtest_running"; state["pending_confirmation"]=None; state["agents"]={**state.get("agents",{}),"research":"complete","backtest":"running","indicator":"running","paper":"gated","approval":"gated","live":"gated"}; _activity(state,"Deterministic Backtest Agent started",f"Testing {spec['symbol']} with deterministic rules.","running"); await save(strategy_id,user_id,token,state,"backtesting")
        rows,source=await _market_data(user_id,strategy_id,token,spec); result=bt(rows,spec); state["data_source"]=source; state["bars_loaded"]=len(rows); state["backtest"]={**result,"symbol":spec["symbol"],"timeframe":spec["timeframe"],"period_days":spec["lookback_days"],"data_source":source}; state["pipeline_stage"]="backtest_complete"; state["pending_confirmation"]="approval"; state["agents"]={**state.get("agents",{}),"research":"complete","backtest":"complete","indicator":"complete","paper":"gated","approval":"current","live":"gated"}; m=result["metrics"]; _activity(state,"Deterministic Backtest complete",f"{m['trade_count']} trades · {m['win_rate']}% win rate · {m['total_return_pct']}% return · {m['max_drawdown_pct']}% max drawdown."); await save(strategy_id,user_id,token,state,"backtest_complete")
    except Exception as exc:
        state=(await load(strategy_id,user_id,token)).get("spec") or {}; state["pipeline_stage"]="backtest_failed"; state["error"]=str(exc); state["agents"]={**state.get("agents",{}),"backtest":"failed"}; _activity(state,"Deterministic Backtest failed",str(exc)[:240],"failed"); await save(strategy_id,user_id,token,state,"backtest_failed")

async def run_pipeline(strategy_id,user_id,token): await run_research(strategy_id,user_id,token)

@api_router.get("/status/{strategy_id}")
async def status(strategy_id,user=Depends(get_current_user)):
    token=user.get("_access_token") or user.get("access_token")
    if not token: raise HTTPException(401,"Missing access token")
    strategy=await load(strategy_id,user["id"],token); state=strategy.get("spec") or {}
    return {"strategy_id":strategy_id,"status":strategy.get("status"),"pipeline_stage":state.get("pipeline_stage"),"agents":state.get("agents",{}),"activity":state.get("activity",[]),"research":state.get("research"),"backtest":state.get("backtest"),"data_source":state.get("data_source"),"bars_loaded":state.get("bars_loaded"),"error":state.get("error")}
