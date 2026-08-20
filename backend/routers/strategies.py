"""
/api/strategies — CRUD for trading strategies.
Strategy creation is intentionally fast: naming is deterministic and does
not wait on an LLM. LLM work belongs to the actual research/agent pipeline,
not to the initial save operation.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user

api_router = APIRouter(prefix="/api/strategies", tags=["strategies"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    os.getenv(
        "SUPABASE_PUBLISHABLE_KEY",
        "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X",
    ),
)


def _sb_headers(access_token: str | None = None):
    """Build valid Supabase REST headers for either RLS or service-role access.

    When a user JWT is available, Authorization uses that JWT so the request
    remains RLS-scoped. The `apikey` header must still always contain a
    Supabase project API key; a user access token is not a replacement for it.
    """
    authorization_token = access_token or SUPABASE_SERVICE_KEY
    apikey = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY

    if not authorization_token or not apikey:
        raise HTTPException(
            status_code=500,
            detail="Supabase database credentials are not configured",
        )

    return {
        "apikey": apikey,
        "Authorization": f"Bearer {authorization_token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _derive_strategy_name(raw_text: str) -> str:
    """Create a useful strategy label locally without an LLM round-trip."""
    text = re.sub(r"\s+", " ", raw_text.strip())
    if not text:
        return "Untitled Strategy"

    identifiers: list[str] = []
    for pattern in (
        r"\bBTC\s*/?\s*USD\b",
        r"\bETH\s*/?\s*USD\b",
        r"\b[A-Z]{2,6}\s*/\s*[A-Z]{2,6}\b",
        r"\b\d+(?:\.\d+)?\s*(?:EMA|SMA|RSI|ATR|MACD)\b",
        r"\b(?:EMA|SMA|RSI|ATR|MACD)\s*\(?\d+(?:\.\d+)?\)?\b",
    ):
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = re.sub(r"\s+", " ", match).strip()
            if value and value.lower() not in {x.lower() for x in identifiers}:
                identifiers.append(value.upper())

    if identifiers:
        label = " ".join(identifiers[:3])
        if len(label) <= 48:
            return label

    words = re.findall(r"[A-Za-z0-9/%.-]+", text)
    label = " ".join(words[:6]).strip(" .,-")
    return label[:48] or "Untitled Strategy"


class CreateStrategyRequest(BaseModel):
    raw_strategy_text: str


@api_router.get("")
async def list_strategies(user=Depends(get_current_user)):
    user_id = user["id"]
    access_token = user.get("_access_token")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/strategies",
            headers=_sb_headers(access_token),
            params={"user_id": f"eq.{user_id}", "order": "created_at.desc"},
        )
    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Could not fetch strategies")
    return resp.json()


@api_router.post("")
async def create_strategy(
    req: CreateStrategyRequest,
    user=Depends(get_current_user),
):
    user_id = user["id"]
    access_token = user.get("_access_token")
    raw_text = req.raw_strategy_text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="Strategy text cannot be empty")

    strategy_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    strategy_name = _derive_strategy_name(raw_text)

    # IMPORTANT: do not call the LLM here. This endpoint is the hot path
    # behind the New Strategy modal and should return as soon as the durable
    # strategy record exists. Research/Backtest/Paper stages should run as
    # an asynchronous workflow after creation.
    payload = {
        "strategy_id": strategy_id,
        "user_id": user_id,
        "name": strategy_name,
        "raw_strategy_text": raw_text,
        "status": "draft",
        "fast_track": False,
        "heightened_monitoring_day": None,
        "heightened_monitoring_total": None,
        "created_at": now,
        "updated_at": now,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/strategies",
            headers=_sb_headers(access_token),
            json=payload,
        )

    if not resp.is_success:
        raise HTTPException(
            status_code=502,
            detail=f"Could not save strategy: {resp.text[:200]}",
        )

    return {
        "strategy_id": strategy_id,
        "name": strategy_name,
        "status": "draft",
        "fast_track": False,
        "heightened_monitoring_day": None,
        "heightened_monitoring_total": None,
        "pipeline_started": False,
        "message": "Strategy saved. Start the asynchronous research pipeline next.",
    }
