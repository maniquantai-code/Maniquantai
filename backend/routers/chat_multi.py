"""Compatibility wrapper that keeps the existing gated chat while allowing
MT5, another broker API, or Yahoo Finance as the market-data source."""
from . import chat as legacy
import os
import httpx

SB=os.getenv("SUPABASE_URL","https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
ANON=os.getenv("SUPABASE_ANON_KEY","sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X").strip()

def _h(token): return {"apikey":ANON,"Authorization":f"Bearer {token}","Content-Type":"application/json"}

async def market_data_available(uid,token):
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.get(f"{SB}/rest/v1/broker_accounts",headers=_h(token),params={"user_id":f"eq.{uid}","select":"id","limit":"1"})
    if not r.is_success: raise legacy.HTTPException(502,"Could not verify your market-data connections")
    # No connector is also valid: the pipeline will use Yahoo Finance.
    return True


def connected_confirmation(x):
    v=legacy.norm(x)
    return v in {"connected","mt5 connected","broker connected","api connected","broker api connected","done"} or "connected" in v

legacy.mt5_connected=market_data_available
legacy.connected_confirmation=connected_confirmation
legacy.SYSTEM=legacy.SYSTEM.replace("your connected MetaTrader 5 account first; the configured fallback is used only when the MT5 feed fails","your selected MT5 or broker API first; another connected source is tried next, then Yahoo Finance")
api_router=legacy.api_router
