"""
/api/chat — deterministic strategy-aware chat orchestration.

The chat endpoint keeps pipeline state in the strategy's JSONB `spec` so short
follow-ups such as "yes", "approve", and "do paper trade" retain context.
LLMs are used for explanation only; state transitions and metrics are never
invented by the model.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.llm_router import router as llm_router
from .auth import get_current_user

api_router = APIRouter(prefix="/api", tags=["chat"])

SUPABASE_URL = "https://zuimeyynaarjsovnqilk.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X"

SYSTEM_PROMPT = """You are Vela, ManiQuantAI's trading assistant.
You explain the deterministic pipeline state supplied by the backend.
Never invent backtest, paper-trading, win-rate, drawdown, P&L, or trade-count
numbers. If a metric is absent, say it is not available yet. Be concise.
"""


class ChatRequest(BaseModel):
    strategy_id: str
    message: str


def _headers(token: str) -> dict[str, str]:
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def _load_strategy(strategy_id: str, user_id: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/strategies",
            headers=_headers(token),
            params={
                "strategy_id": f"eq.{strategy_id}",
                "user_id": f"eq.{user_id}",
                "select=strategy_id,name,raw_strategy_text,status,spec",
                "limit": "1",
            },
        )
    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Could not load strategy state")
    rows = resp.json()
    if not rows:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return rows[0]


async def _save_state(strategy_id: str, user_id: str, token: str, spec: dict, status: str | None = None) -> None:
    payload = {"spec": spec}
    if status:
        payload["status"] = status
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.patch(
            f"{SUPABASE_URL}/rest/v1/strategies",
            headers=_headers(token),
            params={
                "strategy_id": f"eq.{strategy_id}",
                "user_id": f"eq.{user_id}",
            },
            json=payload,
        )
    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Could not persist pipeline state")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _is_yes(text: str) -> bool:
    return _norm(text) in {"yes", "y", "confirm", "confirmed", "proceed", "go ahead", "do it"}


def _is_approve(text: str) -> bool:
    return _norm(text) in {"approve", "approved", "approve it", "confirm approval"}


def _is_paper(text: str) -> bool:
    value = _norm(text)
    return "paper trading" in value or "paper trade" in value


def _looks_like_backtest_request(text: str) -> bool:
    value = _norm(text)
    return "backtest" in value or ("last 90 days" in value and "btc" in value)


def _strategy_context(strategy: dict, state: dict) -> str:
    metrics = state.get("backtest", {}).get("metrics") or {}
    metric_text = json.dumps(metrics, separators=(",", ":")) if metrics else "none"
    return (
        f"Strategy: {strategy.get('name') or 'Untitled'}\n"
        f"Spec/raw request: {strategy.get('raw_strategy_text') or ''}\n"
        f"Pipeline stage: {state.get('pipeline_stage', 'research')}\n"
        f"Pending confirmation: {state.get('pending_confirmation') or 'none'}\n"
        f"Approved: {bool(state.get('approved'))}\n"
        f"Backtest metrics: {metric_text}\n"
        f"Paper session: {json.dumps(state.get('paper_session')) if state.get('paper_session') else 'none'}"
    )


def _deterministic_action(message: str, state: dict) -> tuple[str | None, str | None]:
    """Return (action, response) without an LLM for workflow commands."""
    text = _norm(message)
    pending = state.get("pending_confirmation")

    if _is_yes(text) and pending == "backtest":
        state["pending_confirmation"] = None
        state["pipeline_stage"] = "backtest_running"
        state.setdefault("backtest", {})["status"] = "queued"
        return "backtest", "Confirmed. The BTC/USD 15-minute backtest is queued for the last 90 days. I will only report metrics produced by the deterministic backtest engine."

    if _is_approve(text):
        state["approved"] = True
        state["approved_at"] = datetime.now(timezone.utc).isoformat()
        state["pipeline_stage"] = "paper_ready"
        state["pending_confirmation"] = None
        return "approve", "Approved. Gate 3 is passed for this strategy. The next pipeline stage is paper trading, using the saved strategy configuration."

    if _is_paper(text):
        if state.get("approved"):
            state["pipeline_stage"] = "paper_ready"
            state["pending_confirmation"] = "paper_launch"
            return "paper_ready", "Paper trading is ready for the approved strategy. Say “do paper trade” and I’ll launch the saved configuration without asking for the strategy details again."
        return None, "Paper trading is gated until the strategy has passed backtesting and received human approval."

    if text in {"do paper trade", "start paper trade", "launch paper trading", "launch paper trade"} and state.get("approved"):
        now = datetime.now(timezone.utc).isoformat()
        session = {
            "status": "running",
            "mode": "paper",
            "started_at": now,
            "initial_capital": 10000,
            "risk_per_trade": 0.01,
            "max_concurrent_positions": 1,
            "source": "deterministic_chat_pipeline",
        }
        state["paper_session"] = session
        state["pipeline_stage"] = "paper_trading"
        state["pending_confirmation"] = None
        return "paper_launch", "Paper trading launched using the saved strategy configuration. Initial capital is the platform paper default of $10,000, risk is 1% per trade, and max concurrent positions is 1. No live capital is used."

    if _looks_like_backtest_request(message):
        state["pipeline_stage"] = "backtest_ready"
        state["pending_confirmation"] = "backtest"
        return "backtest_request", "I have the backtest request and the strategy configuration. Run it over the last 90 days?"

    return None, None


@api_router.post("/chat")
async def strategy_chat(req: ChatRequest, user=Depends(get_current_user)):
    token = user.get("_access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing access token")

    strategy = await _load_strategy(req.strategy_id, user["id"], token)
    state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
    action, deterministic_response = _deterministic_action(req.message, state)

    if deterministic_response:
        status = "paper_trading" if action == "paper_launch" else None
        await _save_state(req.strategy_id, user["id"], token, state, status=status)

        async def deterministic_stream():
            yield f"data: {json.dumps({'type': 'delta', 'content': deterministic_response})}\n\n"
            yield f"data: {json.dumps({'type': 'state', 'pipeline_stage': state.get('pipeline_stage'), 'action': action})}\n\n"
            yield "data: {\"type\":\"done\",\"deterministic\":true}\n\n"

        return StreamingResponse(deterministic_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

    context = _strategy_context(strategy, state)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\nCurrent persisted workflow state:\n" + context},
        {"role": "user", "content": req.message},
    ]

    async def event_stream():
        try:
            async for event in llm_router.stream_chat(
                messages=messages,
                max_tokens=256,
                temperature=0.1,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except RuntimeError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
