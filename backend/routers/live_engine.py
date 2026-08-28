"""Bridge-driven live strategy scanner and signal queue.

The Windows MT5 agent owns market-data access. It asks this API for the
user's explicitly approved strategies, evaluates deterministic conditions
locally against live MT5 candles, and posts only validated signals here.
This API never invents a strategy and never bypasses live approval.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

api_router = APIRouter(prefix="/api/mt5-bridge", tags=["live-engine"])
SB = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
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
    risk_percent: float | None = Field(default=None, ge=0, le=5)
    deviation: int = Field(default=20, ge=0, le=500)
    magic: int = Field(default=260821, ge=1)
    reason: str = Field(min_length=1, max_length=500)
    signal_key: str = Field(min_length=8, max_length=160)


@api_router.get("/live-strategies")
async def live_strategies(authorization: str | None = Header(default=None)):
    token = _token(authorization)
    rows = await _rpc("mt5_live_strategies", {"p_token_hash": _hash(token)})
    return {"strategies": rows if isinstance(rows, list) else []}


@api_router.post("/live-signal")
async def live_signal(req: SignalRequest, authorization: str | None = Header(default=None)):
    token = _token(authorization)
    side = req.side.lower()
    if side not in {"buy", "sell", "close", "close_buy", "close_sell"}:
        raise HTTPException(400, "Unsupported live signal side")
    body = req.model_dump()
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
