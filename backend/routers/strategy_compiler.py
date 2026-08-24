"""Authenticated strategy compilation endpoint."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from ..core.strategy_compiler import compile_strategy
from .auth import get_current_user

api_router = APIRouter(prefix="/api/strategy", tags=["strategy"])

class CompileRequest(BaseModel):
    strategy: str = Field(min_length=1, max_length=12000)

@api_router.post("/compile")
async def compile(req: CompileRequest, user=Depends(get_current_user)):
    try:
        spec = await compile_strategy(req.strategy)
        return {"ok": True, "spec": spec}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Strategy compilation failed: {str(exc)[:300]}")
