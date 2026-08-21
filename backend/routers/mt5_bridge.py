"""Secure MT5 bridge job queue."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user

api_router = APIRouter(prefix="/api/mt5-bridge", tags=["mt5-bridge"])
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
BRIDGE_PEPPER = os.getenv("MT5_BRIDGE_PEPPER", "")


def _service_headers():
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(503, "MT5 bridge service is temporarily unavailable")
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _fernet() -> Fernet:
    key = os.getenv("FERNET_KEY", "").strip()
    if key:
        return Fernet(key.encode())
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(503, "MT5 bridge encryption is not configured")
    derived = base64.urlsafe_b64encode(
        hashlib.sha256(("maniquantai-mt5:" + SUPABASE_SERVICE_ROLE_KEY).encode()).digest()
    )
    return Fernet(derived)


def _decrypt(blob: str) -> dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(blob.encode()).decode())
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(500, "Stored MT5 account data could not be read") from exc


def _encrypt(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return _fernet().encrypt(raw).decode()


def _hash(token: str) -> str:
    return hashlib.sha256((BRIDGE_PEPPER + token).encode()).hexdigest()


class Complete(BaseModel):
    token: str
    job_id: str
    rates: list[dict[str, Any]]
    account: dict[str, Any] | None = None


class Fail(BaseModel):
    token: str
    error: str


async def _account(user_id: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/broker_accounts",
            headers=_service_headers(),
            params={
                "user_id": f"eq.{user_id}",
                "connector_type": "eq.mt5",
                "select": "id,user_id,encrypted_payload",
                "order": "created_at.desc",
                "limit": "1",
            },
        )
    if not r.is_success or not r.json():
        return None
    return r.json()[0]


@api_router.post("/register")
async def register(user=Depends(get_current_user)):
    """Create a bridge token for the user's saved MT5 account.

    The token is stored only as a hash inside the encrypted credential blob.
    The MT5 password never enters the bridge-token response.
    """
    token = secrets.token_urlsafe(32)
    existing = await _account(user["id"])
    if not existing:
        raise HTTPException(404, "Connect your MetaTrader 5 account first")

    creds = _decrypt(existing["encrypted_payload"])
    creds["bridge_token_hash"] = _hash(token)
    creds["bridge_enabled"] = True

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(
            f"{SUPABASE_URL}/rest/v1/broker_accounts",
            headers=_service_headers(),
            params={"id": f"eq.{existing['id']}", "user_id": f"eq.{user['id']}"},
            json={"encrypted_payload": _encrypt(creds)},
        )
    if not r.is_success:
        raise HTTPException(502, "Could not register the MT5 bridge")
    return {"bridge_token": token, "broker_account_id": existing["id"]}


async def _find_bridge(token: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/broker_accounts",
            headers=_service_headers(),
            params={
                "connector_type": "eq.mt5",
                "select": "id,user_id,encrypted_payload",
                "limit": "100",
            },
        )
    if not r.is_success:
        raise HTTPException(502, "MT5 bridge registry unavailable")

    target = _hash(token)
    for row in r.json():
        creds = _decrypt(row["encrypted_payload"])
        if hmac.compare_digest(str(creds.get("bridge_token_hash", "")), target) and creds.get("bridge_enabled"):
            return row
    raise HTTPException(401, "Invalid MT5 bridge token")


@api_router.get("/jobs")
async def jobs(token: str):
    acct = await _find_bridge(token)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/mt5_bridge_jobs",
            headers=_service_headers(),
            params={
                "user_id": f"eq.{acct['user_id']}",
                "status": "eq.queued",
                "expires_at": f"gt.{datetime.now(timezone.utc).isoformat()}",
                "select": "id,symbol,timeframe,date_from,date_to",
                "order": "created_at.asc",
                "limit": "3",
            },
        )
    if not r.is_success:
        raise HTTPException(502, "Could not load MT5 bridge jobs")

    jobs = r.json()
    ids = [x["id"] for x in jobs]
    if ids:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.patch(
                f"{SUPABASE_URL}/rest/v1/mt5_bridge_jobs",
                headers=_service_headers(),
                params={
                    "id": f"in.({','.join(ids)})",
                    "user_id": f"eq.{acct['user_id']}",
                    "status": "eq.queued",
                },
                json={"status": "processing", "updated_at": datetime.now(timezone.utc).isoformat()},
            )
    return {"jobs": jobs}


async def _complete(job_id: str, token: str, payload: dict):
    acct = await _find_bridge(token)
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.patch(
            f"{SUPABASE_URL}/rest/v1/mt5_bridge_jobs",
            headers=_service_headers(),
            params={"id": f"eq.{job_id}", "user_id": f"eq.{acct['user_id']}"},
            json=payload,
        )
    if not r.is_success:
        raise HTTPException(502, "Could not save MT5 bridge result")
    return {"ok": True}


@api_router.post("/jobs/{job_id}/complete")
async def complete(job_id: str, req: Complete):
    if req.job_id != job_id:
        raise HTTPException(400, "Job mismatch")
    return await _complete(
        job_id,
        req.token,
        {"status": "complete", "rates": req.rates, "account": req.account, "updated_at": datetime.now(timezone.utc).isoformat()},
    )


@api_router.post("/jobs/{job_id}/fail")
async def fail(job_id: str, req: Fail):
    if req.job_id != job_id:
        raise HTTPException(400, "Job mismatch")
    return await _complete(
        job_id,
        req.token,
        {"status": "failed", "error": req.error[:1000], "updated_at": datetime.now(timezone.utc).isoformat()},
    )
