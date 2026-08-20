"""
/api/broker-accounts — manage MT5 / Delta Exchange / CoinSwitch connections.
Passwords are encrypted with Fernet before storage.
"""

from __future__ import annotations

import os
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import httpx

from .auth import get_current_user

api_router = APIRouter(prefix="/api/broker-accounts", tags=["broker-accounts"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Generate a key if not set (persist this in env in production!)
_FERNET_KEY = os.getenv("FERNET_KEY", Fernet.generate_key().decode())
_fernet = Fernet(_FERNET_KEY.encode())


def _sb_headers():
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


class MT5ConnectRequest(BaseModel):
    login: int
    password: str
    server: str
    label: str | None = None


@api_router.get("")
async def list_accounts(user=Depends(get_current_user)):
    user_id = user["id"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/broker_accounts",
            headers=_sb_headers(),
            params={"user_id": f"eq.{user_id}", "select": "id,connector_type,connector_name,label,created_at"},
        )
    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Could not fetch broker accounts")
    return resp.json()


@api_router.post("/mt5")
async def connect_mt5(req: MT5ConnectRequest, user=Depends(get_current_user)):
    user_id = user["id"]
    encrypted_password = _encrypt(req.password)

    import uuid
    payload = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "connector_type": "mt5",
        "connector_name": "MetaTrader 5",
        "label": req.label,
        "credentials": {
            "login": req.login,
            "password_enc": encrypted_password,
            "server": req.server,
        },
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/broker_accounts",
            headers=_sb_headers(),
            json=payload,
        )

    if not resp.is_success:
        raise HTTPException(status_code=502, detail=f"Could not save account: {resp.text[:200]}")

    created = resp.json()
    return {"broker_account_id": created[0]["id"] if created else payload["id"]}


@api_router.delete("/{account_id}")
async def disconnect_account(account_id: str, user=Depends(get_current_user)):
    user_id = user["id"]

    # Verify ownership
    async with httpx.AsyncClient(timeout=10) as client:
        check = await client.get(
            f"{SUPABASE_URL}/rest/v1/broker_accounts",
            headers=_sb_headers(),
            params={"id": f"eq.{account_id}", "user_id": f"eq.{user_id}"},
        )

    if not check.is_success or not check.json():
        raise HTTPException(status_code=404, detail="Account not found or not yours")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{SUPABASE_URL}/rest/v1/broker_accounts",
            headers=_sb_headers(),
            params={"id": f"eq.{account_id}"},
        )

    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Could not delete account")

    return {"deleted": True}
