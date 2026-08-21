"""
/api/broker-accounts — manage MT5 connections.

MT5 credentials are encrypted before they are persisted. The web backend does
not attempt to connect to MT5: the local Windows bridge does that on the
user's machine.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import get_current_user

api_router = APIRouter(prefix="/api/broker-accounts", tags=["broker-accounts"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def _fernet() -> Fernet:
    key = os.getenv("FERNET_KEY", "").strip()
    if key:
        return Fernet(key.encode())
    # Stable emergency fallback so a missing Vercel FERNET_KEY does not create
    # a new random encryption key on every cold start. The service-role key is
    # never exposed to the client.
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Broker encryption is not configured")
    derived = base64.urlsafe_b64encode(
        hashlib.sha256(("maniquantai-mt5:" + SUPABASE_SERVICE_ROLE_KEY).encode()).digest()
    )
    return Fernet(derived)


def _sb_headers():
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(503, "Trading account storage is temporarily unavailable")
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _encrypt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return _fernet().encrypt(raw).decode()


class MT5ConnectRequest(BaseModel):
    login: int = Field(gt=0)
    password: str = Field(min_length=1)
    server: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=100)


@api_router.get("")
async def list_accounts(user=Depends(get_current_user)):
    user_id = user["id"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/broker_accounts",
            headers=_sb_headers(),
            params={
                "user_id": f"eq.{user_id}",
                "select": "id,connector_type,connector_name,label,created_at,last_verified_at",
                "order": "created_at.desc",
            },
        )
    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Could not fetch trading accounts")
    return resp.json()


@api_router.post("/mt5")
async def connect_mt5(req: MT5ConnectRequest, user=Depends(get_current_user)):
    """Persist MT5 credentials and let the local bridge verify/connect them."""
    user_id = user["id"]
    account_id = str(uuid.uuid4())
    encrypted_payload = _encrypt({
        "login": req.login,
        "password": req.password,
        "server": req.server.strip(),
    })
    payload = {
        "id": account_id,
        "user_id": user_id,
        "connector_type": "mt5",
        "connector_name": "MetaTrader 5",
        "label": req.label,
        "encrypted_payload": encrypted_payload,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SUPABASE_URL}/rest/v1/broker_accounts",
                headers=_sb_headers(),
                json=payload,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not reach trading account storage") from exc

    if not resp.is_success:
        # Never return the database response because it may contain sensitive
        # implementation details.
        raise HTTPException(status_code=502, detail="Could not save the MT5 connection")

    created = resp.json()
    return {"broker_account_id": created[0]["id"] if created else account_id}


@api_router.delete("/{account_id}")
async def disconnect_account(account_id: str, user=Depends(get_current_user)):
    user_id = user["id"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{SUPABASE_URL}/rest/v1/broker_accounts",
            headers=_sb_headers(),
            params={"id": f"eq.{account_id}", "user_id": f"eq.{user_id}"},
        )
    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Could not disconnect the trading account")
    return {"deleted": True}
