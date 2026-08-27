"""
Auth helpers — verifies Supabase JWTs passed as Bearer tokens.
"""

from __future__ import annotations

import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx

bearer_scheme = HTTPBearer(auto_error=False)

SUPABASE_URL = os.getenv(
    "SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co"
).rstrip("/")
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X",
).strip()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or not credentials.credentials.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )

    token = credentials.credentials.strip()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": SUPABASE_ANON_KEY,
            },
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = resp.json()
    # Keep the verified token in two explicit fields. Some downstream code
    # serializes user dictionaries, so use a plain field name as the canonical
    # value and retain the underscored alias for backwards compatibility.
    user["access_token"] = token
    user["_access_token"] = token
    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict | None:
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None
