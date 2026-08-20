"""
/api/chat — strategy chat endpoint consumed by the frontend ChatPanel.
Uses the LLM router so it always uses the best available free model.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.llm_router import router as llm_router
from .auth import get_current_user

api_router = APIRouter(prefix="/api", tags=["chat"])

SYSTEM_PROMPT = """You are Vela, ManiQuantAI's trading assistant.
You help users understand their algorithmic trading strategies — backtests,
paper trading results, drawdown, win rates, and risk metrics.

Rules you always follow:
1. Never guarantee profits or specific returns.
2. Always mention both win rate AND avg win/loss ratio together — never one without the other.
3. Flag suspicious backtest results (e.g. >85% win rate, <1% drawdown).
4. Be concise, precise, and honest.
5. If you don't know something, say so — don't fabricate numbers.
"""


class ChatRequest(BaseModel):
    strategy_id: str
    message: str


@api_router.post("/chat")
async def strategy_chat(
    req: ChatRequest,
    user=Depends(get_current_user),
):
    try:
        result = await llm_router.chat(
            messages=[{"role": "user", "content": req.message}],
            system_prompt=SYSTEM_PROMPT,
            max_tokens=1024,
            temperature=0.3,
        )
        return {
            "reply": result["content"],
            "model_used": result["model_display"],
            "attempts": result.get("attempts", 1),
        }
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="All AI models are temporarily unavailable. Trading execution continues — chat will resume shortly.",
        )
