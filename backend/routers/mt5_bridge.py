"""Secure MT5 bridge job queue and token lifecycle."""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .auth import get_current_user

api_router = APIRouter(prefix="/api/mt5-bridge", tags=["mt5-bridge"])
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
BRIDGE_PEPPER = os.getenv("MT5_BRIDGE_PEPPER", "").strip()
BRIDGE_ONLINE_SECONDS = 15
BRIDGE_TOKEN_DAYS = 30


def _api_headers(token: str | None = None) -> dict[str, str]:
    if not SUPABASE_ANON_KEY:
        raise HTTPException(503, "MT5 bridge service is temporarily unavailable")
    headers = {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _hash(token: str) -> str:
    return hashlib.sha256((BRIDGE_PEPPER + token).encode()).hexdigest()


def _new_token() -> tuple[str, str, str]:
    token = "mqai_mt5_" + secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=BRIDGE_TOKEN_DAYS)).isoformat()
    return token, _hash(token), expires_at


class Complete(BaseModel):
    token: str
    job_id: str
    rates: list[dict[str, Any]]
    account: dict[str, Any] | None = None


class Fail(BaseModel):
    token: str
    error: str


class ExecutionComplete(BaseModel):
    token: str
    job_id: str
    result: dict[str, Any]


class ExecutionRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: str
    volume: float = Field(gt=0)
    stop_loss: float | None = None
    take_profit: float | None = None
    deviation: int = Field(default=20, ge=0, le=500)
    magic: int = Field(default=260821, ge=1)
    comment: str = Field(default="ManiQuantAI", max_length=31)


async def _rpc(name: str, payload: dict[str, Any], token: str | None = None, timeout: float = 15) -> Any:
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{SUPABASE_URL}/rest/v1/rpc/{name}", headers=_api_headers(token), json=payload)
    if not r.is_success:
        raise HTTPException(502, f"MT5 bridge operation failed: {r.text[:500]}")
    return r.json()


@api_router.post("/register")
async def register(user=Depends(get_current_user)):
    token, token_hash, expires_at = _new_token()
    result = await _rpc("mt5_register_bridge", {"p_token_hash": token_hash, "p_expires_at": expires_at}, token=user["access_token"])
    return {"bridge_token": token, "broker_account_id": result.get("broker_account_id"), "expires_at": expires_at}


@api_router.post("/refresh")
async def refresh(user=Depends(get_current_user)):
    token, token_hash, expires_at = _new_token()
    result = await _rpc("mt5_rotate_bridge", {"p_token_hash": token_hash, "p_expires_at": expires_at}, token=user["access_token"])
    return {"bridge_token": token, "broker_account_id": result.get("broker_account_id"), "expires_at": expires_at}


@api_router.post("/revoke")
async def revoke(user=Depends(get_current_user)):
    return await _rpc("mt5_revoke_bridge", {}, token=user["access_token"])


@api_router.get("/status")
async def status(user=Depends(get_current_user)):
    return await _rpc("mt5_bridge_status", {}, token=user["access_token"])


@api_router.get("/jobs")
async def jobs(token: str):
    result = await _rpc("mt5_claim_jobs", {"p_token_hash": _hash(token)}, timeout=15)
    return {"jobs": result if isinstance(result, list) else []}


async def _complete(job_id: str, token: str, *, status: str, rates=None, account=None, error=None, result=None):
    await _rpc("mt5_complete_job", {"p_token_hash": _hash(token), "p_job_id": job_id, "p_status": status, "p_rates": rates, "p_account": account, "p_error": error, "p_result": result}, timeout=30)
    return {"ok": True}


@api_router.post("/jobs/{job_id}/complete")
async def complete(job_id: str, req: Complete):
    if req.job_id != job_id:
        raise HTTPException(400, "Job mismatch")
    return await _complete(job_id, req.token, status="complete", rates=req.rates, account=req.account)


@api_router.post("/jobs/{job_id}/fail")
async def fail(job_id: str, req: Fail):
    if not req.error:
        raise HTTPException(400, "Bridge failure reason is required")
    return await _complete(job_id, req.token, status="failed", error=req.error[:1000])


async def _bridge_online(user_id: str, access_token: str) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=BRIDGE_ONLINE_SECONDS)).isoformat()
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/broker_accounts", headers=_api_headers(access_token), params={"user_id": f"eq.{user_id}", "connector_type": "eq.mt5", "bridge_enabled": "eq.true", "last_verified_at": f"gte.{cutoff}", "select": "id", "limit": "1"})
    if not r.is_success:
        raise HTTPException(502, "Could not verify the MetaTrader 5 bridge")
    return bool(r.json())


@api_router.post("/execution")
async def queue_execution(req: ExecutionRequest, strategy_id: str, user=Depends(get_current_user)):
    if req.side.lower() not in {"buy", "sell"}:
        raise HTTPException(400, "Order side must be buy or sell")
    if not await _bridge_online(user["id"], user["access_token"]):
        raise HTTPException(409, "MetaTrader 5 bridge is offline. Start the Windows bridge before sending a live order.")
    try:
        job_id = await _rpc("mt5_queue_execution", {"p_strategy_id": strategy_id, "p_symbol": req.symbol.upper(), "p_timeframe": "15m", "p_request": req.model_dump(), "p_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()}, token=user["access_token"], timeout=15)
    except HTTPException as exc:
        if exc.status_code == 502 and "Live trading is waiting" in str(exc.detail):
            raise HTTPException(409, "Live trading is waiting for your explicit approval")
        raise
    return {"status": "queued", "job_id": job_id, "message": "Live order queued for your online MetaTrader 5 bridge."}


@api_router.post("/execution/{job_id}/complete")
async def execution_complete(job_id: str, req: ExecutionComplete):
    if req.job_id != job_id:
        raise HTTPException(400, "Job mismatch")
    return await _complete(job_id, req.token, status="complete", result=req.result)


@api_router.post("/execution/{job_id}/fail")
async def execution_fail(job_id: str, req: Fail):
    return await _complete(job_id, req.token, status="failed", error=req.error[:1000])
