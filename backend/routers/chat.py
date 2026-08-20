"""
/api/chat — fast strategy chat endpoint consumed by the frontend ChatPanel.

The response is streamed as Server-Sent Events so the user sees the first
model tokens immediately instead of waiting for the full completion.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.llm_router import router as llm_router
from .auth import get_current_user

api_router = APIRouter(prefix="/api", tags=["chat"])

SYSTEM_PROMPT = """You are Vela, ManiQuantAI's trading assistant.
You help users understand algorithmic trading strategies, backtests,
paper-trading results, drawdown, win rates, and risk metrics.

Rules:
1. Never guarantee profits or specific returns.
2. Always mention both win rate AND avg win/loss ratio together when discussing results.
3. Flag suspicious backtest results.
4. Be concise, precise, and honest.
5. Never invent numbers.
6. For a strategy request, give a short acknowledgement and focus on the next pipeline step.
"""


class ChatRequest(BaseModel):
    strategy_id: str
    message: str


@api_router.post("/chat")
async def strategy_chat(
    req: ChatRequest,
    user=Depends(get_current_user),
):
    async def event_stream():
        try:
            async for event in llm_router.stream_chat(
                messages=[{"role": "user", "content": req.message}],
                system_prompt=SYSTEM_PROMPT,
                max_tokens=384,
                temperature=0.2,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except RuntimeError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
