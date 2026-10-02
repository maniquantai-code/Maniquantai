"""Bridge-driven live strategy scanner and signal queue.

The Windows MT5 agent owns market-data access. It asks this API for the
user's explicitly approved strategies, evaluates deterministic conditions
locally against live MT5 candles, and posts only validated signals here.
This API never invents a strategy and never bypasses live approval.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

api_router = APIRouter(prefix="/api/mt5-bridge", tags=["live-engine"])
SB = os.getenv("SUPABASE_URL", "").rstrip("/")
ANON = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY") or "").strip()
PEPPER = os.getenv("MT5_BRIDGE_PEPPER", "").strip()


def _headers() -> dict[str, str]:
    if not ANON:
        raise HTTPException(500, "Supabase publishable key is not configured")
    return {"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}


def _token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Bridge token required")
    token = authorization[7:].strip()
    if len(token) < 16:
        raise HTTPException(401, "Invalid bridge token")
    return token


def _hash(token: str) -> str:
    return hashlib.sha256((PEPPER + token).encode()).hexdigest()


def _certificate_hash(certificate: str) -> str:
    return hashlib.sha256(certificate.encode()).hexdigest()


async def _rpc(name: str, payload: dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{SB}/rest/v1/rpc/{name}", headers=_headers(), json=payload)
    if not r.is_success:
        raise HTTPException(401 if r.status_code in (401, 403) else 502, r.text[:500])
    return r.json()


class SignalRequest(BaseModel):
    strategy_id: str
    symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(min_length=1, max_length=8)
    side: str
    volume: float = Field(gt=0)
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_percent: float | None = Field(default=None, gt=0, le=2)
    deviation: int = Field(default=20, ge=0, le=500)
    magic: int = Field(default=260821, ge=1)
    reason: str = Field(min_length=1, max_length=500)
    signal_key: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    execution_certificate: str = Field(min_length=40, max_length=160)
    execution_snapshot_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    execution_nonce: uuid.UUID


@api_router.get("/live-strategies")
async def live_strategies(authorization: str | None = Header(default=None)):
    token = _token(authorization)
    token_hash = _hash(token)
    rows = await _rpc("mt5_live_strategies", {"p_token_hash": token_hash})
    strategies = rows if isinstance(rows, list) else []

    # Issue a short-lived certificate bound to the exact server-side strategy
    # snapshot. The plaintext certificate is only returned to the already
    # authenticated bridge; the database stores only its SHA-256 hash.
    manifests = await _rpc("mt5_execution_manifest", {"p_token_hash": token_hash})
    manifest_by_id = {
        str(x.get("strategy_id")): x for x in (manifests if isinstance(manifests, list) else [])
    }
    enriched = []
    for strategy in strategies:
        sid = str(strategy.get("strategy_id") or "")
        manifest = manifest_by_id.get(sid)
        if not manifest:
            continue
        certificate = "mqai_cert_" + secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        await _rpc("mt5_issue_execution_certificate", {
            "p_token_hash": token_hash,
            "p_strategy_id": sid,
            "p_snapshot_hash": manifest["snapshot_hash"],
            "p_certificate_hash": _certificate_hash(certificate),
            "p_expires_at": expires_at.isoformat(),
        })
        enriched.append({
            **strategy,
            "execution_certificate": certificate,
            "execution_certificate_expires_at": expires_at.isoformat(),
            "execution_snapshot_hash": manifest["snapshot_hash"],
        })
    return {"strategies": enriched}


@api_router.post("/live-signal")
async def live_signal(req: SignalRequest, authorization: str | None = Header(default=None)):
    token = _token(authorization)
    if not SB:
        raise HTTPException(503, "Supabase URL is not configured")
    side = req.side.lower()
    if side not in {"buy", "sell", "close", "close_buy", "close_sell"}:
        raise HTTPException(400, "Unsupported live signal side")
    if side in {"buy", "sell"} and (req.stop_loss is None or req.take_profit is None):
        raise HTTPException(422, "Protective stop-loss and take-profit are required for entry signals")
    if req.risk_percent is None and side in {"buy", "sell"}:
        raise HTTPException(422, "risk_percent is required for entry signals")
    certificate_hash = _certificate_hash(req.execution_certificate)
    await _rpc("mt5_authorize_live_signal", {
        "p_token_hash": _hash(token),
        "p_strategy_id": req.strategy_id,
        "p_snapshot_hash": req.execution_snapshot_hash,
        "p_certificate_hash": certificate_hash,
        "p_nonce": str(req.execution_nonce),
        "p_signal_key": req.signal_key,
    })
    body = req.model_dump()
    body.pop("execution_certificate", None)
    body.pop("execution_snapshot_hash", None)
    body.pop("execution_nonce", None)
    body["symbol"] = req.symbol.upper()
    job_id = await _rpc("mt5_queue_live_signal", {
        "p_token_hash": _hash(token),
        "p_strategy_id": req.strategy_id,
        "p_symbol": req.symbol.upper(),
        "p_timeframe": req.timeframe,
        "p_request": body,
        "p_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
    })
    if job_id is None:
        return {"ok": True, "status": "duplicate_or_in_flight", "message": "A live execution job for this strategy is already queued or processing."}
    return {"ok": True, "status": "queued", "job_id": job_id, "message": "Approved live signal queued for MetaTrader 5 execution."}
