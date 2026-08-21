"""
/api/broker-accounts — manage MT5 connections.

MT5 credentials are encrypted before persistence. The web backend stores the
connection; the Windows bridge is responsible for the actual terminal session.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import get_current_user

api_router = APIRouter(prefix="/api/broker-accounts", tags=["broker-accounts"])
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
# The publishable key is safe to use for RLS-scoped requests. Keep the same
# fallback as the auth/strategy routers so a missing Vercel env var does not
# produce an invalid/empty `apikey` header. A service-role key, when configured,
# remains server-side and is preferred for server-owned operations.
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    os.getenv(
        "SUPABASE_PUBLISHABLE_KEY",
        "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X",
    ),
).strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    key = os.getenv("FERNET_KEY", "").strip()
    if key:
        return Fernet(key.encode())
    # Deterministic fallback keeps existing installations working while the
    # service-role secret remains server-side only.
    material = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    if not material:
        raise HTTPException(503, "Trading account storage is not configured")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("maniquantai-mt5:" + material).encode()).digest()))


def _sb_headers(access_token: str | None = None):
    """Build valid Supabase REST headers without ever emitting `Bearer `."""
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    token = SUPABASE_SERVICE_ROLE_KEY or (access_token or "").strip()
    if not key or not token:
        raise HTTPException(503, "Trading account storage is not configured")
    return {
        "apikey": key,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _user_token(user: dict) -> str | None:
    return (user.get("access_token") or user.get("_access_token") or "").strip() or None


def _encrypt(payload: dict) -> str:
    return _fernet().encrypt(json.dumps(payload, separators=(",", ":")).encode()).decode()


class MT5ConnectRequest(BaseModel):
    login: int = Field(gt=0)
    password: str = Field(min_length=1, max_length=512)
    server: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=100)


@api_router.get("")
async def list_accounts(user=Depends(get_current_user)):
    uid = user["id"]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{SUPABASE_URL}/rest/v1/broker_accounts",
                headers=_sb_headers(_user_token(user)),
                params={
                    "user_id": f"eq.{uid}",
                    "connector_type": "eq.mt5",
                    "select": "id,connector_type,connector_name,label,created_at,last_verified_at",
                    "order": "created_at.desc",
                },
            )
    except httpx.RequestError as exc:
        logger.exception("MT5 account list request failed")
        raise HTTPException(502, "Trading account storage could not be reached") from exc
    if not r.is_success:
        logger.error("broker list failed status=%s body=%s", r.status_code, r.text[:1200])
        raise HTTPException(502, "Could not fetch trading accounts")
    return r.json()


@api_router.post("/mt5")
async def connect_mt5(req: MT5ConnectRequest, user=Depends(get_current_user)):
    """Save or replace the user's MT5 connection without reaching MT5 from Vercel."""
    uid = user["id"]
    server = req.server.strip()
    label = req.label.strip() if req.label else None
    try:
        encrypted = _encrypt({"login": req.login, "password": req.password, "server": server})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("MT5 encryption setup failed")
        raise HTTPException(503, "Trading account storage is not configured yet") from exc

    headers = _sb_headers(_user_token(user))
    payload = {
        "user_id": uid,
        "connector_type": "mt5",
        "connector_name": "MetaTrader 5",
        "label": label,
        "encrypted_payload": encrypted,
        "last_verified_at": None,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as c:
            existing = await c.get(
                f"{SUPABASE_URL}/rest/v1/broker_accounts",
                headers=headers,
                params={
                    "user_id": f"eq.{uid}",
                    "connector_type": "eq.mt5",
                    "select": "id",
                    "order": "created_at.desc",
                    "limit": "1",
                },
            )
            if not existing.is_success:
                logger.error("MT5 existing-account lookup failed status=%s body=%s", existing.status_code, existing.text[:1200])
                raise HTTPException(502, "We could not check your saved trading account. Please try again.")

            rows = existing.json() or []
            if rows:
                account_id = rows[0]["id"]
                r = await c.patch(
                    f"{SUPABASE_URL}/rest/v1/broker_accounts",
                    headers=headers,
                    params={"id": f"eq.{account_id}", "user_id": f"eq.{uid}"},
                    json={
                        "connector_type": "mt5",
                        "connector_name": "MetaTrader 5",
                        "label": label,
                        "encrypted_payload": encrypted,
                        "last_verified_at": None,
                    },
                )
                if r.is_success:
                    return {"broker_account_id": account_id, "saved": True, "message": "MetaTrader 5 account linked successfully."}
                logger.error("MT5 account update failed status=%s body=%s", r.status_code, r.text[:1500])
            else:
                r = await c.post(
                    f"{SUPABASE_URL}/rest/v1/broker_accounts",
                    headers=headers,
                    json=payload,
                )
                if r.is_success:
                    rows = r.json() or []
                    if rows:
                        return {"broker_account_id": rows[0]["id"], "saved": True, "message": "MetaTrader 5 account linked successfully."}
                    confirm = await c.get(
                        f"{SUPABASE_URL}/rest/v1/broker_accounts",
                        headers=headers,
                        params={
                            "user_id": f"eq.{uid}",
                            "connector_type": "eq.mt5",
                            "select": "id",
                            "order": "created_at.desc",
                            "limit": "1",
                        },
                    )
                    if confirm.is_success and confirm.json():
                        return {"broker_account_id": confirm.json()[0]["id"], "saved": True, "message": "MetaTrader 5 account linked successfully."}
                logger.error("MT5 account insert failed status=%s body=%s", r.status_code, r.text[:1500])
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        logger.exception("MT5 broker account storage request failed")
        raise HTTPException(502, "Trading account storage could not be reached. Please try again.") from exc

    status = getattr(r, "status_code", 500)
    body = getattr(r, "text", "")[:1500]
    if status in (401, 403):
        raise HTTPException(502, "Your signed-in session could not save this MetaTrader 5 account. Refresh the page, sign in again, and retry.")
    if status == 409:
        raise HTTPException(409, "This MetaTrader 5 account is already linked. Refresh the Brokers section and continue.")
    if "broker_accounts_user_id_fkey" in body:
        raise HTTPException(502, "Your ManiQuantAI profile is still being prepared. Refresh the page and retry the MT5 connection.")
    raise HTTPException(502, "We could not link this MetaTrader 5 account yet. Check the login, password, and server, then try again.")


@api_router.delete("/{account_id}")
async def disconnect_account(account_id: str, user=Depends(get_current_user)):
    uid = user["id"]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.delete(
                f"{SUPABASE_URL}/rest/v1/broker_accounts",
                headers=_sb_headers(_user_token(user)),
                params={"id": f"eq.{account_id}", "user_id": f"eq.{uid}"},
            )
    except httpx.RequestError as exc:
        raise HTTPException(502, "Trading account storage could not be reached") from exc
    if not r.is_success:
        raise HTTPException(502, "Could not disconnect the trading account")
    return {"deleted": True}
