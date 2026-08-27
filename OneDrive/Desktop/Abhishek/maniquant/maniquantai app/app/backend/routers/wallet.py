"""
/api/wallet — credit balance for the current user.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
import httpx

from .auth import get_current_user

api_router = APIRouter(prefix="/api/wallet", tags=["wallet"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    os.getenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X"),
).strip()

FREE_TIER_CREDITS = 80


def _sb_headers(access_token: str | None = None):
    """Use service-role access when configured, otherwise the user's RLS JWT.

    Never construct an Authorization header from an empty service key. The
    previous implementation produced `Bearer ` in production when the
    service-role environment variable was absent, which caused httpx to fail
    before the request even reached Supabase.
    """
    token = SUPABASE_SERVICE_KEY or (access_token or "").strip()
    apikey = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
    if not token or not apikey:
        return None
    return {
        "apikey": apikey,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


@api_router.get("")
async def get_wallet(user=Depends(get_current_user)):
    user_id = user["id"]
    headers = _sb_headers(user.get("_access_token"))
    if headers is None:
        # Keep the UI usable if optional wallet persistence is not configured.
        return {"balance": FREE_TIER_CREDITS, "monthly_allowance": FREE_TIER_CREDITS, "reset_date": None}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/wallets",
            headers=headers,
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
            headers=headers,
            json=payload,
        )

    if create_resp.is_success:
        return create_resp.json()[0] if create_resp.json() else payload

    return {"balance": FREE_TIER_CREDITS, "monthly_allowance": FREE_TIER_CREDITS, "reset_date": None}
