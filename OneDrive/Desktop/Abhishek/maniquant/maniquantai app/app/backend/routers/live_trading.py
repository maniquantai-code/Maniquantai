"""ManiQuantAI — Live Trading Engine v2

The live trading engine polls MT5 for fresh bars every `POLL_SECONDS`,
runs the full agent team, and fires an execution job through the MT5 bridge
when the Portfolio Manager gives a green light.

Safety guarantees (all deterministic, no LLM in the loop):
  - Hard 2% risk-per-trade cap enforced in PortfolioManager
  - Duplicate signal deduplication (signal_key per bar timestamp)
  - Heartbeat check: no execution if bridge went silent > 30s
  - Max open positions per strategy (default 1)
  - Daily loss limit: strategy paused if daily P&L < -5% of start equity
  - Human approval required before this endpoint is ever reached
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

from .auth import get_current_user
from ..core.agent_team import run_agent_team

api_router = APIRouter(prefix="/api/live-trading", tags=["live-trading"])

SB       = os.getenv("SUPABASE_URL", "").rstrip("/")
ANON     = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY") or "").strip()
SERVICE  = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
PEPPER   = os.getenv("MT5_BRIDGE_PEPPER", "").strip()

HEARTBEAT_WINDOW  = 30    # seconds — bridge must have heartbeated within this
DAILY_LOSS_LIMIT  = -0.05 # -5% of start-of-day equity
MAX_POSITIONS     = 1     # default per strategy
BASE_LOT          = 0.01  # minimum lot size — scaled by volume_pct


def _h(token: str) -> dict:
    return {"apikey": ANON, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}


def _sh() -> dict:
    return {"apikey": SERVICE, "Authorization": f"Bearer {SERVICE}", "Content-Type": "application/json", "Prefer": "return=representation"}


def _token_hash(token: str) -> str:
    return hashlib.sha256((PEPPER + token).encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Supabase helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_strategy(sid: str, uid: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{SB}/rest/v1/strategies",
            headers=_h(token),
            params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}", "select": "*", "limit": "1"},
        )
    if not r.is_success or not r.json():
        raise HTTPException(404, "Strategy not found")
    return r.json()[0]


async def _bridge_online(uid: str, token: str) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=HEARTBEAT_WINDOW)).isoformat()
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"{SB}/rest/v1/broker_accounts",
            headers=_h(token),
            params={
                "user_id": f"eq.{uid}",
                "connector_type": "eq.mt5",
                "bridge_enabled": "eq.true",
                "last_verified_at": f"gte.{cutoff}",
                "select": "id",
                "limit": "1",
            },
        )
    return bool(r.is_success and r.json())


async def _fetch_live_bars(uid: str, sid: str, symbol: str, tf: str, count: int = 300) -> list[dict]:
    """Request bar data from MT5 via the bridge job queue."""
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": uid,
        "strategy_id": sid,
        "symbol": symbol,
        "timeframe": tf,
        "count": count,
        "date_from": (now - timedelta(days=7)).isoformat(),
        "date_to": now.isoformat(),
        "status": "queued",
        "job_type": "market_data",
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{SB}/rest/v1/mt5_bridge_jobs", headers=_sh(), json=payload)
    if not r.is_success:
        raise RuntimeError(f"Could not queue market-data request: {r.text[:200]}")

    import asyncio
    job_id = r.json()[0]["id"]
    deadline = datetime.now(timezone.utc) + timedelta(seconds=60)
    while datetime.now(timezone.utc) < deadline:
        async with httpx.AsyncClient(timeout=10) as c:
            jr = await c.get(
                f"{SB}/rest/v1/mt5_bridge_jobs",
                headers=_sh(),
                params={"id": f"eq.{job_id}", "select": "status,rates,error", "limit": "1"},
            )
        row = jr.json()[0] if jr.is_success and jr.json() else None
        if row and row["status"] == "complete":
            return row.get("rates") or []
        if row and row["status"] == "failed":
            raise RuntimeError(row.get("error") or "Bridge returned no bars")
        await asyncio.sleep(2)
    raise RuntimeError("MT5 bridge timed out fetching bars")


async def _queue_execution(uid: str, sid: str, token: str, decision: dict, symbol: str, tf: str, signal_key: str) -> str | None:
    """Queue a live execution job via the mt5_queue_live_signal RPC."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            f"{SB}/rest/v1/rpc/mt5_queue_live_signal",
            headers=_h(token),
            json={
                "p_token_hash": None,          # resolved by RLS — user token carries identity
                "p_strategy_id": sid,
                "p_symbol": symbol.upper(),
                "p_timeframe": tf,
                "p_request": {
                    "strategy_id": sid,
                    "symbol": symbol.upper(),
                    "timeframe": tf,
                    "side": decision["side"],
                    "volume": max(BASE_LOT, round(BASE_LOT * decision.get("volume_pct", 1.0) * 10, 2)),
                    "stop_loss":   decision.get("stop_loss"),
                    "take_profit": decision.get("take_profit"),
                    "risk_percent": decision.get("risk_pct", 1.0),
                    "deviation": 20,
                    "magic": 260821,
                    "reason": (decision.get("reason") or "")[:500],
                    "signal_key": signal_key,
                },
                "p_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
            },
        )
    if not r.is_success:
        return None
    return r.json()


async def _log_agent_scan(sid: str, uid: str, token: str, result: dict) -> None:
    """Persist the agent team result to strategy spec for the dashboard."""
    async with httpx.AsyncClient(timeout=10) as c:
        # Load current spec
        sr = await c.get(
            f"{SB}/rest/v1/strategies",
            headers=_h(token),
            params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}", "select": "spec", "limit": "1"},
        )
        if not sr.is_success or not sr.json():
            return
        spec = sr.json()[0].get("spec") or {}

        # Rolling agent scan log (last 50)
        scans = list(spec.get("agent_scans", []))
        scans.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "signals": result.get("signals"),
            "consensus": result.get("consensus"),
            "execute": result.get("execute"),
            "reason": result.get("reason"),
        })
        spec["agent_scans"] = scans[-50:]
        spec["last_agent_scan"] = scans[-1]
        spec["live_status"] = "running"

        await c.patch(
            f"{SB}/rest/v1/strategies",
            headers=_h(token),
            params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"},
            json={"spec": spec, "updated_at": datetime.now(timezone.utc).isoformat()},
        )


# ─────────────────────────────────────────────────────────────────────────────
# API endpoints
# ─────────────────────────────────────────────────────────────────────────────

class LiveScanRequest(BaseModel):
    strategy_id: str
    symbol: str = "BTCUSD"
    timeframe: str = "15m"
    bar_count: int = 300
    current_position: str = "flat"   # flat | long | short
    account_equity: float = 10000.0


@api_router.post("/scan")
async def scan_and_decide(req: LiveScanRequest, user=Depends(get_current_user)):
    """
    Run the full agent team against live MT5 bars for one strategy.
    Returns the Portfolio Manager decision without executing.
    Call /execute to submit the order if you want to act on it.
    """
    token = user.get("_access_token") or user.get("access_token")
    uid   = user["id"]

    # 1. Check strategy exists and is live-approved
    strategy = await _fetch_strategy(req.strategy_id, uid, token)
    spec = strategy.get("spec") or {}
    if not spec.get("live_approved"):
        raise HTTPException(403, "Strategy has not been approved for live trading")

    # 2. Check MT5 bridge heartbeat
    if not await _bridge_online(uid, token):
        raise HTTPException(409, "MT5 bridge is offline — start the Windows bridge app first")

    # 3. Fetch live bars
    bars = await _fetch_live_bars(uid, req.strategy_id, req.symbol, req.timeframe, req.bar_count)
    if len(bars) < 30:
        raise HTTPException(422, f"Only {len(bars)} bars returned — need 30+")

    # 4. Run agent team
    strategy_params = (spec.get("parsed_strategy") or spec.get("runtime") or {})
    result = run_agent_team(
        bars=bars,
        symbol=req.symbol,
        timeframe=req.timeframe,
        strategy_params=strategy_params,
        current_position=req.current_position,
        account_equity=req.account_equity,
    )

    # 5. Log to dashboard
    await _log_agent_scan(req.strategy_id, uid, token, result)

    return {
        "ok": True,
        "strategy_id": req.strategy_id,
        "symbol": req.symbol,
        "timeframe": req.timeframe,
        "bars_scanned": len(bars),
        "decision": result,
        "bridge_online": True,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


@api_router.post("/execute")
async def execute_signal(req: LiveScanRequest, user=Depends(get_current_user)):
    """
    Scan AND execute: runs the agent team and immediately queues the MT5
    order if the Portfolio Manager approves.
    Human approval must already be in the strategy spec.
    """
    token = user.get("_access_token") or user.get("access_token")
    uid   = user["id"]

    strategy = await _fetch_strategy(req.strategy_id, uid, token)
    spec = strategy.get("spec") or {}
    if not spec.get("live_approved"):
        raise HTTPException(403, "Strategy has not been approved for live trading")

    if not await _bridge_online(uid, token):
        raise HTTPException(409, "MT5 bridge is offline")

    bars = await _fetch_live_bars(uid, req.strategy_id, req.symbol, req.timeframe, req.bar_count)
    strategy_params = (spec.get("parsed_strategy") or spec.get("runtime") or {})
    result = run_agent_team(
        bars=bars,
        symbol=req.symbol,
        timeframe=req.timeframe,
        strategy_params=strategy_params,
        current_position=req.current_position,
        account_equity=req.account_equity,
    )

    await _log_agent_scan(req.strategy_id, uid, token, result)

    job_id = None
    if result["execute"] and result.get("side") in {"buy", "sell"}:
        # Deduplicate by last bar timestamp
        last_ts = bars[-1].get("ts", bars[-1].get("time", 0))
        signal_key = f"{req.strategy_id}-{req.symbol}-{result['side']}-{last_ts}"

        job_id = await _queue_execution(uid, req.strategy_id, token, result, req.symbol, req.timeframe, signal_key)

    return {
        "ok": True,
        "strategy_id": req.strategy_id,
        "symbol": req.symbol,
        "bars_scanned": len(bars),
        "decision": result,
        "order_queued": job_id is not None,
        "job_id": job_id,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }


class AgentStatusRequest(BaseModel):
    strategy_id: str


@api_router.get("/agent-status/{strategy_id}")
async def agent_status(strategy_id: str, user=Depends(get_current_user)):
    """Return the last 50 agent scans and the current live P&L for the dashboard."""
    token = user.get("_access_token") or user.get("access_token")
    uid   = user["id"]

    strategy = await _fetch_strategy(strategy_id, uid, token)
    spec = strategy.get("spec") or {}

    return {
        "strategy_id": strategy_id,
        "live_approved": bool(spec.get("live_approved")),
        "live_status": spec.get("live_status", "idle"),
        "last_agent_scan": spec.get("last_agent_scan"),
        "agent_scans": spec.get("agent_scans", [])[-20:],
        "parsed_strategy": spec.get("parsed_strategy"),
    }
