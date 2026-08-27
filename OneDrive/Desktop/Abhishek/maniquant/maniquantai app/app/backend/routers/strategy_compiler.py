"""Authenticated, recoverable strategy compilation endpoint."""
from __future__ import annotations
from fastapi import APIRouter, Depends
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
        return {"ok": True, "spec": spec, "pipeline_stage": "compiled"}
    except Exception as first_error:
        # One deterministic repair attempt. It must preserve the user's rules;
        # it may only normalize missing executable representation.
        repair_prompt = (
            "Compile the following trading strategy again. Preserve every explicit user rule. "
            "Return JSON only and make every runtime field executable. Required runtime fields: "
            "symbol, timeframe, lookback_days, rsi_period, rsi_entry_below, rsi_exit_above, "
            "bollinger_period, bollinger_std, risk_pct, max_hold_hours, stop_loss, take_profit. "
            "Represent stop_loss and take_profit as deterministic objects when possible. "
            "Do not add indicators or trading rules not requested.\n\nSTRATEGY:\n" + req.strategy
        )
        try:
            spec = await compile_strategy(repair_prompt)
            spec.setdefault("source", {})["original_user_prompt"] = req.strategy
            return {"ok": True, "spec": spec, "pipeline_stage": "compiled", "recovered": True}
        except Exception as second_error:
            return {
                "ok": False,
                "code": "STRATEGY_COMPILATION_FAILED",
                "pipeline_stage": "strategy_compilation_failed",
                "message": "I couldn't convert this strategy into an executable specification yet. No trading action was executed.",
                "recoverable": True,
                "details": str(second_error)[:300],
            }
