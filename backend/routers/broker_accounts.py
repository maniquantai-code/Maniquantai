"""
/api/broker-accounts — manage MT5 connections.

MT5 credentials are encrypted before they are persisted. The web backend does
not attempt to connect to MT5: the local Windows bridge does that on the
user's machine.
"""
from __future__ import annotations
import base64, hashlib, json, logging, os
from cryptography.fernet import Fernet
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .auth import get_current_user

api_router = APIRouter(prefix="/api/broker-accounts", tags=["broker-accounts"])
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
SUPABASE_ANON_KEY = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") or "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
logger = logging.getLogger(__name__)

def _fernet() -> Fernet:
    key = os.getenv("FERNET_KEY", "").strip()
    if key: return Fernet(key.encode())
    material = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("maniquantai-mt5:" + material).encode()).digest()))

def _sb_headers(access_token: str | None = None):
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    if not key: raise HTTPException(503, "Trading account storage is not configured")
    # When a service role is configured, use it server-side so broker-account
    # persistence cannot be broken by client JWT/apikey mismatches. Ownership is
    # still enforced by the explicit user_id filters below.
    return {"apikey": key, "Authorization": f"Bearer {key if SUPABASE_SERVICE_ROLE_KEY else (access_token or key)}", "Content-Type": "application/json", "Prefer": "return=representation"}

def _user_token(user: dict) -> str | None:
    return (user.get("access_token") or user.get("_access_token") or "").strip() or None

def _encrypt(payload: dict) -> str:
    return _fernet().encrypt(json.dumps(payload, separators=(",", ":")).encode()).decode()

class MT5ConnectRequest(BaseModel):
    login: int = Field(gt=0)
    password: str = Field(min_length=1)
    server: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=100)

@api_router.get("")
async def list_accounts(user=Depends(get_current_user)):
    uid=user["id"]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r=await c.get(f"{SUPABASE_URL}/rest/v1/broker_accounts",headers=_sb_headers(_user_token(user)),params={"user_id":f"eq.{uid}","select":"id,connector_type,connector_name,label,created_at,last_verified_at","order":"created_at.desc"})
    except httpx.RequestError as exc: raise HTTPException(502,"Trading account storage could not be reached") from exc
    if not r.is_success:
        logger.error("broker list failed %s %s",r.status_code,r.text[:1000]);raise HTTPException(502,"Could not fetch trading accounts")
    return r.json()

@api_router.post("/mt5")
async def connect_mt5(req: MT5ConnectRequest,user=Depends(get_current_user)):
    uid=user["id"]
    try: encrypted=_encrypt({"login":req.login,"password":req.password,"server":req.server.strip()})
    except Exception as exc:
        logger.exception("MT5 encryption setup failed");raise HTTPException(503,"Trading account storage is not configured yet") from exc
    headers=_sb_headers(_user_token(user))
    payload={"user_id":uid,"connector_type":"mt5","connector_name":"MetaTrader 5","label":req.label,"encrypted_payload":encrypted}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            # Replace the user's existing MT5 record instead of creating a
            # second record on every reconnect. No schema-level uniqueness is
            # required for this path.
            existing=await c.get(f"{SUPABASE_URL}/rest/v1/broker_accounts",headers=headers,params={"user_id":f"eq.{uid}","connector_type":"eq.mt5","select":"id","limit":"1"})
            if existing.is_success and existing.json():
                aid=existing.json()[0]["id"]
                r=await c.patch(f"{SUPABASE_URL}/rest/v1/broker_accounts",headers=headers,params={"id":f"eq.{aid}","user_id":f"eq.{uid}"},json={"connector_name":"MetaTrader 5","label":req.label,"encrypted_payload":encrypted})
                if r.is_success:return {"broker_account_id":aid,"saved":True}
            r=await c.post(f"{SUPABASE_URL}/rest/v1/broker_accounts",headers=headers,json=payload)
    except httpx.RequestError as exc:
        logger.exception("MT5 broker account storage request failed");raise HTTPException(502,"Trading account storage could not be reached") from exc
    if not r.is_success:
        body=r.text[:1500]
        logger.error("MT5 broker_accounts write failed status=%s body=%s user=%s",r.status_code,body,uid)
        if r.status_code in (401,403): raise HTTPException(502,"Your signed-in session could not save this MetaTrader 5 account. Please sign in again and retry.")
        if r.status_code==409: raise HTTPException(409,"This MetaTrader 5 account is already linked. Refresh the Brokers page and continue.")
        if "broker_accounts_user_id_fkey" in body or "profiles" in body: raise HTTPException(502,"Your ManiQuantAI profile is not ready yet. Sign out, sign in again, and retry the MT5 connection.")
        raise HTTPException(502,"MetaTrader 5 account could not be saved. Please verify the account details and try again.")
    created=r.json();return {"broker_account_id":created[0]["id"] if created else None,"saved":True}

@api_router.delete("/{account_id}")
async def disconnect_account(account_id:str,user=Depends(get_current_user)):
    uid=user["id"]
    try:
        async with httpx.AsyncClient(timeout=10) as c:r=await c.delete(f"{SUPABASE_URL}/rest/v1/broker_accounts",headers=_sb_headers(_user_token(user)),params={"id":f"eq.{account_id}","user_id":f"eq.{uid}"})
    except httpx.RequestError as exc: raise HTTPException(502,"Trading account storage could not be reached") from exc
    if not r.is_success: raise HTTPException(502,"Could not disconnect the trading account")
    return {"deleted":True}
