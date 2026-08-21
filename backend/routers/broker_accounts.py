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
import logging
import os

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import get_current_user

api_router = APIRouter(prefix="/api/broker-accounts", tags=["broker-accounts"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
# Prefer the explicitly configured public key. The previous implementation
# incorrectly used the user's JWT as the PostgREST `apikey` when the server
# key was missing, which causes Supabase to return 401 "Invalid API key".
SUPABASE_ANON_KEY = (
    os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X"
).strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    key = os.getenv("FERNET_KEY", "").strip()
    if key:
        return Fernet(key.encode())
    if not SUPABASE_SERVICE_ROLE_KEY:
        # Keep encryption deterministic across deployments when the optional
        # FERNET_KEY is not configured.
        derived = base64.urlsafe_b64encode(
            hashlib.sha256(("maniquantai-mt5:" + SUPABASE_ANON_KEY).encode()).digest()
        )
        return Fernet(derived)
    derived = base64.urlsafe_b64encode(
        hashlib.sha256(("maniquantai-mt5:" + SUPABASE_SERVICE_ROLE_KEY).encode()).digest()
    )
    return Fernet(derived)


def _sb_headers(access_token: str | None = None):
    """Build valid PostgREST headers.

    `apikey` is always the Supabase public/service API key. The user's access
    token is used only as the Authorization bearer when available so RLS can
    still evaluate the authenticated user.
    """
    service_key = SUPABASE_SERVICE_ROLE_KEY
    public_key = SUPABASE_ANON_KEY
    user_token = (access_token or "").strip()
    if service_key:
        return {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
    if not public_key:
        raise HTTPException(status_code=503, detail="Trading account storage is not configured")
    return {
        "apikey": public_key,
        "Authorization": f"Bearer {user_token}" if user_token else f"Bearer {public_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _user_token(user: dict) -> str | None:
    return (user.get("access_token") or user.get("_access_token") or "").strip() or None


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
    try:
        headers = _sb_headers(_user_token(user))
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/broker_accounts",
                headers=headers,
                params={
                    "user_id": f"eq.{user_id}",
                    "select": "id,connector_type,connector_name,label,created_at,last_verified_at",
                    "order": "created_at.desc",
                },
            )
    except httpx.RequestError as exc:
        logger.exception("MT5 account list request failed")
        raise HTTPException(status_code=502, detail="Trading account storage could not be reached") from exc
    if not resp.is_success:
        logger.error("MT5 account list failed: status=%s body=%s user=%s", resp.status_code, resp.text[:1000], user_id)
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
        logger.exception("MT5 encryption setup failed")
        raise HTTPException(status_code=503, detail="Trading account storage is not configured yet") from exc

    payload = {
        "user_id": user_id,
        "connector_type": "mt5",
        "connector_name": "MetaTrader 5",
        "label": req.label,
        "encrypted_payload": encrypted_payload,
    }

    try:
        headers = _sb_headers(_user_token(user))
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SUPABASE_URL}/rest/v1/broker_accounts",
                headers=headers,
                json=payload,
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        logger.exception("MT5 broker account storage request failed")
        raise HTTPException(status_code=502, detail="Trading account storage could not be reached") from exc

    if not resp.is_success:
        logger.error(
            "MT5 broker_accounts insert failed: status=%s body=%s user=%s",
            resp.status_code, resp.text[:1000], user_id,
        )
        if resp.status_code in (401, 403):
            raise HTTPException(status_code=502, detail="Your signed-in session could not save this MetaTrader 5 account")
        if resp.status_code == 409:
            raise HTTPException(status_code=409, detail="This MetaTrader 5 account is already linked")
        raise HTTPException(status_code=502, detail="MetaTrader 5 account could not be saved. Please try again.")

    created = resp.json()
    return {"broker_account_id": created[0]["id"] if created else None}


@api_router.delete("/{account_id}")
async def disconnect_account(account_id: str, user=Depends(get_current_user)):
    user_id = user["id"]
    try:
        headers = _sb_headers(_user_token(user))
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(
                f"{SUPABASE_URL}/rest/v1/broker_accounts",
                headers=headers,
                params={"id": f"eq.{account_id}", "user_id": f"eq.{user_id}"},
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Trading account storage could not be reached") from exc
    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Could not disconnect the trading account")
    return {"deleted": True}
