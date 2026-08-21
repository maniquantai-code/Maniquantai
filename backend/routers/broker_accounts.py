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

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import get_current_user

api_router = APIRouter(prefix="/api/broker-accounts", tags=["broker-accounts"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def _fernet() -> Fernet:
    key = os.getenv("FERNET_KEY", "").strip()
    if key:
        return Fernet(key.encode())
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("MT5 connection encryption is not configured on the backend")
    derived = base64.urlsafe_b64encode(
        hashlib.sha256(("maniquantai-mt5:" + SUPABASE_SERVICE_ROLE_KEY).encode()).digest()
    )
    return Fernet(derived)


def _sb_headers(access_token: str | None = None):
    # Prefer the service role for server-side writes. If it is not configured,
    # use the verified user's Supabase access token so RLS can authorize the
    # user's own broker_accounts row instead of failing with a generic save error.
    token = SUPABASE_SERVICE_ROLE_KEY or (access_token or "")
    if not token:
        raise HTTPException(status_code=503, detail="Trading account storage is not configured")
    return {
        "apikey": token,
        "Authorization": f"Bearer {token}",
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
            headers=_sb_headers(user.get("_access_token")),
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
    """Persist MT5 credentials for the authenticated user."""
    user_id = user["id"]
    try:
        encrypted_payload = _encrypt({
            "login": req.login,
            "password": req.password,
            "server": req.server.strip(),
        })
    except Exception as exc:
        raise HTTPException(status_code=503, detail="MT5 connection storage is not configured yet") from exc

    # Let Postgres generate the UUID. This avoids unnecessary client-side key
    # handling and keeps the insert aligned with the live schema.
    payload = {
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
                headers=_sb_headers(user.get("_access_token")),
                json=payload,
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Trading account storage could not be reached") from exc

    if not resp.is_success:
        # Log the real Supabase response server-side, but do not expose the
        # response body because it can contain implementation details.
        import logging
        logging.getLogger(__name__).error(
            "MT5 broker_accounts insert failed: status=%s body=%s user=%s",
            resp.status_code, resp.text[:1000], user_id,
        )
        if resp.status_code in (401, 403):
            raise HTTPException(status_code=502, detail="Your session is not authorized to save this trading account")
        if resp.status_code == 409:
            raise HTTPException(status_code=409, detail="This MT5 connection is already linked")
        raise HTTPException(status_code=502, detail="Trading account could not be saved. Please try again.")

    created = resp.json()
    return {"broker_account_id": created[0]["id"] if created else None}


@api_router.delete("/{account_id}")
async def disconnect_account(account_id: str, user=Depends(get_current_user)):
    user_id = user["id"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{SUPABASE_URL}/rest/v1/broker_accounts",
            headers=_sb_headers(user.get("_access_token")),
            params={"id": f"eq.{account_id}", "user_id": f"eq.{user_id}"},
        )
    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Could not disconnect the trading account")
    return {"deleted": True}
