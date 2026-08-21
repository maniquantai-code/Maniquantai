"""Secure MT5 bridge job queue for market data and approved live orders."""
from __future__ import annotations
import base64, hashlib, hmac, json, os, secrets
from datetime import datetime, timezone
from typing import Any
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .auth import get_current_user

api_router = APIRouter(prefix="/api/mt5-bridge", tags=["mt5-bridge"])
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
BRIDGE_PEPPER = os.getenv("MT5_BRIDGE_PEPPER", "")

def _service_headers():
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(503, "MT5 bridge service is temporarily unavailable")
    return {"apikey": SUPABASE_SERVICE_ROLE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}

def _fernet() -> Fernet:
    from cryptography.fernet import Fernet
    key = os.getenv("FERNET_KEY", "").strip()
    if key: return Fernet(key.encode())
    if not SUPABASE_SERVICE_ROLE_KEY: raise HTTPException(503, "MT5 bridge encryption is not configured")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("maniquantai-mt5:" + SUPABASE_SERVICE_ROLE_KEY).encode()).digest()))

def _decrypt(blob: str) -> dict[str, Any]:
    from cryptography.fernet import InvalidToken
    try: return json.loads(_fernet().decrypt(blob.encode()).decode())
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc: raise HTTPException(500, "Stored MT5 account data could not be read") from exc

def _encrypt(payload: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(payload, separators=(",", ":")).encode()).decode()

def _hash(token: str) -> str: return hashlib.sha256((BRIDGE_PEPPER + token).encode()).hexdigest()

class Complete(BaseModel):
    token: str; job_id: str; rates: list[dict[str, Any]]; account: dict[str, Any] | None = None
class Fail(BaseModel):
    token: str; error: str
class ExecutionComplete(BaseModel):
    token: str; job_id: str; result: dict[str, Any]
class ExecutionRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: str
    volume: float = Field(gt=0)
    stop_loss: float | None = None
    take_profit: float | None = None
    deviation: int = Field(default=20, ge=0, le=500)
    magic: int = Field(default=260821, ge=1)
    comment: str = Field(default="ManiQuantAI", max_length=31)

async def _account(user_id: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/broker_accounts", headers=_service_headers(), params={"user_id": f"eq.{user_id}", "connector_type": "eq.mt5", "select": "id,user_id,encrypted_payload", "order": "created_at.desc", "limit": "1"})
    if not r.is_success or not r.json(): return None
    return r.json()[0]

@api_router.post("/register")
async def register(user=Depends(get_current_user)):
    token = secrets.token_urlsafe(32); existing = await _account(user["id"])
    if not existing: raise HTTPException(404, "Connect your MetaTrader 5 account first")
    creds = _decrypt(existing["encrypted_payload"]); creds["bridge_token_hash"] = _hash(token); creds["bridge_enabled"] = True
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(f"{SUPABASE_URL}/rest/v1/broker_accounts", headers=_service_headers(), params={"id": f"eq.{existing['id']}", "user_id": f"eq.{user['id']}"}, json={"encrypted_payload": _encrypt(creds)})
    if not r.is_success: raise HTTPException(502, "Could not register the MT5 bridge")
    return {"bridge_token": token, "broker_account_id": existing["id"]}

async def _find_bridge(token: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/broker_accounts", headers=_service_headers(), params={"connector_type": "eq.mt5", "select": "id,user_id,encrypted_payload", "limit": "100"})
    if not r.is_success: raise HTTPException(502, "MT5 bridge registry unavailable")
    target = _hash(token)
    for row in r.json():
        creds = _decrypt(row["encrypted_payload"])
        if hmac.compare_digest(str(creds.get("bridge_token_hash", "")), target) and creds.get("bridge_enabled"): return row
    raise HTTPException(401, "Invalid MT5 bridge token")

@api_router.get("/jobs")
async def jobs(token: str):
    acct = await _find_bridge(token)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/mt5_bridge_jobs", headers=_service_headers(), params={"user_id": f"eq.{acct['user_id']}", "status": "eq.queued", "expires_at": f"gt.{datetime.now(timezone.utc).isoformat()}", "select": "id,job_type,symbol,timeframe,date_from,date_to,request", "order": "created_at.asc", "limit": "5"})
    if not r.is_success: raise HTTPException(502, "Could not load MT5 bridge jobs")
    jobs = r.json(); ids = [x["id"] for x in jobs]
    if ids:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.patch(f"{SUPABASE_URL}/rest/v1/mt5_bridge_jobs", headers=_service_headers(), params={"id": f"in.({','.join(ids)})", "user_id": f"eq.{acct['user_id']}", "status": "eq.queued"}, json={"status": "processing", "updated_at": datetime.now(timezone.utc).isoformat()})
    return {"jobs": jobs}

async def _complete(job_id: str, token: str, payload: dict):
    acct = await _find_bridge(token)
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.patch(f"{SUPABASE_URL}/rest/v1/mt5_bridge_jobs", headers=_service_headers(), params={"id": f"eq.{job_id}", "user_id": f"eq.{acct['user_id']}"}, json=payload)
    if not r.is_success: raise HTTPException(502, "Could not save MT5 bridge result")
    return {"ok": True}

@api_router.post("/jobs/{job_id}/complete")
async def complete(job_id: str, req: Complete):
    if req.job_id != job_id: raise HTTPException(400, "Job mismatch")
    return await _complete(job_id, req.token, {"status": "complete", "rates": req.rates, "account": req.account, "updated_at": datetime.now(timezone.utc).isoformat()})

@api_router.post("/jobs/{job_id}/fail")
async def fail(job_id: str, req: Fail):
    if req.job_id != job_id: raise HTTPException(400, "Job mismatch")
    return await _complete(job_id, req.token, {"status": "failed", "error": req.error[:1000], "updated_at": datetime.now(timezone.utc).isoformat()})

@api_router.post("/execution")
async def queue_execution(req: ExecutionRequest, strategy_id: str, user=Depends(get_current_user)):
    """Queue a real MT5 order only after explicit server-side live approval."""
    token = user.get("_access_token") or user.get("access_token")
    if not token: raise HTTPException(401, "Your session has expired. Please sign in again.")
    if req.side.lower() not in {"buy", "sell"}: raise HTTPException(400, "Order side must be buy or sell")
    # Read strategy through the user's authenticated session so a user cannot
    # submit another user's strategy ID.
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/strategies", headers={"apikey": os.getenv("SUPABASE_ANON_KEY", ""), "Authorization": f"Bearer {token}"}, params={"strategy_id": f"eq.{strategy_id}", "user_id": f"eq.{user['id']}", "select":"strategy_id,status,spec", "limit":"1"})
    if not r.is_success or not r.json(): raise HTTPException(404, "Strategy not found")
    row = r.json()[0]; spec = row.get("spec") or {}
    if row.get("status") != "live_approved" or spec.get("live_approved") is not True or not spec.get("approved_at"):
        raise HTTPException(409, "Live trading is waiting for your explicit approval")
    acct = await _account(user["id"])
    if not acct: raise HTTPException(409, "Connect your MetaTrader 5 account before starting live trading")
    payload = {"user_id": user["id"], "strategy_id": strategy_id, "job_type": "execution", "status": "queued", "symbol": req.symbol.upper(), "timeframe": spec.get("parsed_strategy", {}).get("timeframe", "15m"), "request": req.model_dump(), "expires_at": datetime.now(timezone.utc).isoformat()}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{SUPABASE_URL}/rest/v1/mt5_bridge_jobs", headers=_service_headers(), json=payload)
    if not r.is_success: raise HTTPException(502, "Could not queue the MT5 live order")
    return {"status":"queued", "job_id":r.json()[0]["id"], "message":"Live order sent to your MetaTrader 5 bridge."}

@api_router.post("/execution/{job_id}/complete")
async def execution_complete(job_id: str, req: ExecutionComplete):
    if req.job_id != job_id: raise HTTPException(400, "Job mismatch")
    return await _complete(job_id, req.token, {"status":"complete", "result":req.result, "updated_at":datetime.now(timezone.utc).isoformat()})

@api_router.post("/execution/{job_id}/fail")
async def execution_fail(job_id: str, req: Fail):
    if req.job_id != job_id: raise HTTPException(400, "Job mismatch")
    return await _complete(job_id, req.token, {"status":"failed", "error":req.error[:1000], "updated_at":datetime.now(timezone.utc).isoformat()})
