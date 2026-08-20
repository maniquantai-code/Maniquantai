"""
/api/wallet — credit balance for the current user.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
import httpx

from .auth import get_current_user

api_router = APIRouter(prefix="/api/wallet", tags=["wallet"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

FREE_TIER_CREDITS = 80


def _sb_headers():
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


@api_router.get("")
async def get_wallet(user=Depends(get_current_user)):
    user_id = user["id"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/wallets",
            headers=_sb_headers(),
            params={"user_id": f"eq.{user_id}"},
        )

    if resp.is_success and resp.json():
        return resp.json()[0]

    # Auto-create wallet for new users
    reset_date = (datetime.utcnow() + timedelta(days=30)).isoformat()
    payload = {
        "user_id": user_id,
        "balance": FREE_TIER_CREDITS,
        "monthly_allowance": FREE_TIER_CREDITS,
        "reset_date": reset_date,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        create_resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/wallets",
            headers=_sb_headers(),
            json=payload,
        )

    if create_resp.is_success:
        return create_resp.json()[0] if create_resp.json() else payload

    return {"balance": FREE_TIER_CREDITS, "monthly_allowance": FREE_TIER_CREDITS, "reset_date": None}
