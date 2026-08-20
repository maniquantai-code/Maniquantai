"""
/api/strategies — CRUD for trading strategies.
Uses the LLM router to kick off research when a strategy is created.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user
from ..core.llm_router import router as llm_router

import httpx

api_router = APIRouter(prefix="/api/strategies", tags=["strategies"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def _sb_headers():
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


class CreateStrategyRequest(BaseModel):
    raw_strategy_text: str


@api_router.get("")
async def list_strategies(user=Depends(get_current_user)):
    user_id = user["id"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/strategies",
            headers=_sb_headers(),
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
    strategy_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    # 1. Ask LLM to parse & name the strategy
    try:
        parse_result = await llm_router.chat(
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Parse this trading strategy and return a short name (max 6 words) "
                        f"and a one-sentence summary.\n\nStrategy: {req.raw_strategy_text}\n\n"
                        f"Reply in JSON: {{\"name\": \"...\", \"summary\": \"...\"}}"
                    ),
                }
            ],
            require_json=True,
            max_tokens=128,
            temperature=0.1,
        )
        import json, re
        raw = parse_result["content"]
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(match.group()) if match else {}
        strategy_name = parsed.get("name", req.raw_strategy_text[:50])
    except Exception:
        strategy_name = req.raw_strategy_text[:50]

    # 2. Save to Supabase
    payload = {
        "strategy_id": strategy_id,
        "user_id": user_id,
        "name": strategy_name,
        "raw_strategy_text": req.raw_strategy_text,
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
            headers=_sb_headers(),
            json=payload,
        )

    if not resp.is_success:
        raise HTTPException(
            status_code=502,
            detail=f"Could not save strategy: {resp.text[:200]}",
        )

    return {"strategy_id": strategy_id, "name": strategy_name, "status": "draft"}
