"""Compatibility wrapper that keeps the existing gated chat while routing
research/backtesting through MT5, another broker API, or Yahoo Finance.
"""
from . import chat as legacy
from .pipeline_multi import run_research as multi_run_research, run_backtest as multi_run_backtest
import os
from datetime import datetime, timezone, timedelta
import httpx

SB=os.getenv("SUPABASE_URL","https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
ANON=os.getenv("SUPABASE_ANON_KEY","sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X").strip()
BRIDGE_ONLINE_SECONDS=15

def _h(token): return {"apikey":ANON,"Authorization":f"Bearer {token}","Content-Type":"application/json"}

async def market_data_available(uid,token):
    cutoff=(datetime.now(timezone.utc)-timedelta(seconds=BRIDGE_ONLINE_SECONDS)).isoformat()
    async with httpx.AsyncClient(timeout=10) as c:
        mt5=await c.get(f"{SB}/rest/v1/broker_accounts",headers=_h(token),params={"user_id":f"eq.{uid}","connector_type":"eq.mt5","bridge_enabled":"eq.true","last_verified_at":f"gte.{cutoff}","select":"id","limit":"1"})
        if mt5.is_success and mt5.json():
            return True
        api=await c.get(f"{SB}/rest/v1/broker_accounts",headers=_h(token),params={"user_id":f"eq.{uid}","connector_type":"eq.broker_api","select":"id","limit":"1"})
    if api.is_success and api.json():
        return True
    # No live connector is available. The deterministic pipeline may still
    # use its configured Yahoo Finance fallback for research/backtesting.
    return True

def connected_confirmation(x):
    v=legacy.norm(x)
    return v in {"connected","mt5 connected","broker connected","api connected","broker api connected","done"} or "connected" in v

legacy.mt5_connected=market_data_available
legacy.connected_confirmation=connected_confirmation
legacy.run_research=multi_run_research
legacy.run_backtest=multi_run_backtest
legacy.SYSTEM=legacy.SYSTEM.replace("your connected MetaTrader 5 account first; the configured fallback is used only when the MT5 feed fails","your selected MT5 or broker API first; another connected source is tried next, then Yahoo Finance")
api_router=legacy.api_router
