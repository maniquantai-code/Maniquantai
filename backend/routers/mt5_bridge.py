"""Secure MT5 bridge job queue."""
from __future__ import annotations
import hashlib, hmac, os, secrets
from datetime import datetime, timezone
from typing import Any
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .auth import get_current_user

api_router = APIRouter(prefix="/api/mt5-bridge", tags=["mt5-bridge"])
SUPABASE_URL=os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co")
SUPABASE_ANON_KEY=os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
BRIDGE_PEPPER=os.getenv("MT5_BRIDGE_PEPPER", "")

def _headers(token: str|None=None):
    return {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token or SUPABASE_ANON_KEY}", "Content-Type":"application/json", "Prefer":"return=representation"}
def _service_headers():
    return {"apikey": SUPABASE_SERVICE_ROLE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}", "Content-Type":"application/json", "Prefer":"return=representation"}
def _hash(token: str)->str:
    return hashlib.sha256((BRIDGE_PEPPER+token).encode()).hexdigest()

class Complete(BaseModel):
    token:str
    job_id:str
    rates:list[dict[str,Any]]
    account:dict[str,Any]|None=None
class Fail(BaseModel):
    token:str
    error:str

async def _account(user_id:str, access_token:str):
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.get(f"{SUPABASE_URL}/rest/v1/broker_accounts",headers=_headers(access_token),params={"user_id":f"eq.{user_id}","connector_type":"eq.mt5","select":"id,credentials","limit":"1"})
    if not r.is_success or not r.json(): return None
    return r.json()[0]

@api_router.post("/register")
async def register(user=Depends(get_current_user)):
    token=secrets.token_urlsafe(32)
    existing=await _account(user["id"],user.get("_access_token"))
    if not existing: raise HTTPException(404,"Connect your MetaTrader 5 account first")
    creds=existing.get("credentials") or {}
    creds={**creds,"bridge_token_hash":_hash(token),"bridge_enabled":True}
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.patch(f"{SUPABASE_URL}/rest/v1/broker_accounts",headers=_headers(user.get("_access_token")),params={"id":f"eq.{existing['id']}","user_id":f"eq.{user['id']}"},json={"credentials":creds})
    if not r.is_success: raise HTTPException(502,"Could not register MT5 bridge")
    return {"bridge_token":token,"broker_account_id":existing["id"]}

async def _find_bridge(token:str):
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.get(f"{SUPABASE_URL}/rest/v1/broker_accounts",headers=_service_headers(),params={"connector_type":"eq.mt5","select":"id,user_id,credentials","limit":"100"})
    if not r.is_success: raise HTTPException(502,"Bridge registry unavailable")
    target=_hash(token)
    for row in r.json():
        creds=row.get("credentials") or {}
        if hmac.compare_digest(creds.get("bridge_token_hash", ""),target) and creds.get("bridge_enabled"):
            return row
    raise HTTPException(401,"Invalid bridge token")

@api_router.get("/jobs")
async def jobs(token:str):
    acct=await _find_bridge(token)
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.get(f"{SUPABASE_URL}/rest/v1/mt5_bridge_jobs",headers=_service_headers(),params={"user_id":f"eq.{acct['user_id']}","status":"eq.queued","expires_at":f"gt.{datetime.now(timezone.utc).isoformat()}","select":"id,symbol,timeframe,date_from,date_to","order":"created_at.asc","limit":"3"})
    if not r.is_success: raise HTTPException(502,"Could not load bridge jobs")
    jobs=r.json(); ids=[x["id"] for x in jobs]
    if ids:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.patch(f"{SUPABASE_URL}/rest/v1/mt5_bridge_jobs",headers=_service_headers(),params={"id":f"in.({','.join(ids)})","user_id":f"eq.{acct['user_id']}","status":"eq.queued"},json={"status":"processing","updated_at":datetime.now(timezone.utc).isoformat()})
    return {"jobs":jobs}

async def _complete(job_id:str, token:str, payload:dict):
    acct=await _find_bridge(token)
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.patch(f"{SUPABASE_URL}/rest/v1/mt5_bridge_jobs",headers=_service_headers(),params={"id":f"eq.{job_id}","user_id":f"eq.{acct['user_id']}"},json=payload)
    if not r.is_success: raise HTTPException(502,"Could not save MT5 bridge result")
    return {"ok":True}

@api_router.post("/jobs/{job_id}/complete")
async def complete(job_id:str, req:Complete):
    if req.job_id!=job_id: raise HTTPException(400,"Job mismatch")
    return await _complete(job_id,req.token,{"status":"complete","rates":req.rates,"account":req.account,"updated_at":datetime.now(timezone.utc).isoformat()})

@api_router.post("/jobs/{job_id}/fail")
async def fail(job_id:str, req:Fail):
    if req.job_id!=job_id: raise HTTPException(400,"Job mismatch")
    return await _complete(job_id,req.token,{"status":"failed","error":req.error[:1000],"updated_at":datetime.now(timezone.utc).isoformat()})
