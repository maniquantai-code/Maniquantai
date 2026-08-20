"""
/api/llm/* endpoints
- GET  /api/llm/health   → health status of all models
- POST /api/llm/test     → send a test message through the router
- POST /api/llm/chat     → main chat endpoint (used by agents internally)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.llm_router import router as llm_router

api_router = APIRouter(prefix="/api/llm", tags=["llm"])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@api_router.get("/health")
async def get_llm_health():
    """Returns real-time availability of all registered LLM models."""
    statuses = await llm_router.health_status()
    available_count = sum(1 for s in statuses if s["available"])
    return {
        "status": "ok" if available_count > 0 else "degraded",
        "available_models": available_count,
        "total_models": len(statuses),
        "models": statuses,
    }


# ---------------------------------------------------------------------------
# Test endpoint
# ---------------------------------------------------------------------------

class TestRequest(BaseModel):
    prompt: str = "Respond with exactly one word: ready"
    use_reasoning: bool = False


@api_router.post("/test")
async def test_llm(req: TestRequest):
    """Fire a quick message through the router to verify end-to-end."""
    try:
        result = await llm_router.chat(
            messages=[{"role": "user", "content": req.prompt}],
            max_tokens=64,
            use_reasoning=req.use_reasoning,
        )
        return {"status": "ok", **result}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------------------------------------------------------------------
# Chat (used by agents and frontend chat panel)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    messages: list[dict]
    system_prompt: str | None = None
    require_json: bool = False
    max_tokens: int = 2048
    temperature: float = 0.2
    use_reasoning: bool = False


@api_router.post("/chat")
async def chat(req: ChatRequest):
    """
    Route a chat request through the LLM router with automatic fallback.
    This is the internal endpoint agents call.
    """
    try:
        result = await llm_router.chat(
            messages=req.messages,
            system_prompt=req.system_prompt,
            require_json=req.require_json,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            use_reasoning=req.use_reasoning,
        )
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
