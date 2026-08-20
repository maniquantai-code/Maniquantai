"""
ManiQuantAI LLM Router
======================
Keeps trading workflows running 24/7 by automatically routing to the best
available free model via OpenRouter, with circuit-breaker fallback.

Priority order (all free, via OpenRouter):
  1. openai/gpt-oss-20b                  (fast, strong reasoning, first choice)
  2. nvidia/nemotron-3-ultra-550b-a55b   (largest, deep reasoning fallback)
  3. nvidia/nemotron-3.5-lightning        (fast, good reasoning)
  4. google/gemma-4-26b-a4b-it            (solid last-resort fallback)

Claude is reserved as a future paid tier — slot is pre-wired.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger("llm_router")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY = "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"

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

class ModelTier(str, Enum):
    FREE_OSS = "free_oss"
    PAID      = "paid"        # Claude — reserved for future use


@dataclass
class ModelConfig:
    model_id: str
    display_name: str
    tier: ModelTier
    supports_json: bool = True
    supports_reasoning: bool = False
    timeout_s: float = 60.0
    priority: int = 0          # lower = tried first


# Ordered by priority (0 = tried first)
MODEL_REGISTRY: list[ModelConfig] = [
    ModelConfig(
        model_id="openai/gpt-oss-20b:free",
        display_name="GPT-OSS 20B",
        tier=ModelTier.FREE_OSS,
        supports_reasoning=True,
        timeout_s=60.0,
        priority=0,
    ),
    ModelConfig(
        model_id="nvidia/nemotron-3-ultra-550b-a55b:free",
        display_name="Nemotron Ultra 550B",
        tier=ModelTier.FREE_OSS,
        supports_reasoning=True,
        timeout_s=90.0,
        priority=1,
    ),
    ModelConfig(
        model_id="nvidia/nemotron-3.5-lightning:free",
        display_name="Nemotron Lightning",
        tier=ModelTier.FREE_OSS,
        supports_reasoning=True,
        timeout_s=45.0,
        priority=2,
    ),
    ModelConfig(
        model_id="google/gemma-4-26b-a4b-it:free",
        display_name="Gemma 4 26B",
        tier=ModelTier.FREE_OSS,
        supports_reasoning=False,
        timeout_s=45.0,
        priority=3,
    ),
    # --- Future paid tier (not active yet) ---
    # ModelConfig(
    #     model_id="anthropic/claude-sonnet-4-6",
    #     display_name="Claude Sonnet 4.6",
    #     tier=ModelTier.PAID,
    #     supports_reasoning=True,
    #     timeout_s=60.0,
    #     priority=10,
    # ),
]


# ---------------------------------------------------------------------------
# Circuit breaker per model
# ---------------------------------------------------------------------------

COOLDOWN_S = 120   # how long a failed model is marked unavailable


@dataclass
class ModelHealth:
    config: ModelConfig
    failures: int = 0
    last_failure_ts: float = 0.0
    total_requests: int = 0
    total_successes: int = 0

    @property
    def is_available(self) -> bool:
        if self.failures == 0:
            return True
        cooldown_elapsed = (time.time() - self.last_failure_ts) > COOLDOWN_S
        if cooldown_elapsed:
            self.failures = 0          # reset circuit after cooldown
        return self.failures < 3       # allow up to 3 consecutive failures

    def record_success(self):
        self.failures = 0
        self.total_requests += 1
        self.total_successes += 1

    def record_failure(self):
        self.failures += 1
        self.last_failure_ts = time.time()
        self.total_requests += 1

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.total_successes / self.total_requests


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class LLMRouter:
    """
    Singleton router. Call `await router.chat(messages, ...)` from anywhere.
    """

    def __init__(self):
        self._health: dict[str, ModelHealth] = {
            m.model_id: ModelHealth(config=m)
            for m in sorted(MODEL_REGISTRY, key=lambda x: x.priority)
        }
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict],
        *,
        require_json: bool = False,
        system_prompt: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        use_reasoning: bool = False,
    ) -> dict[str, Any]:
        """
        Send a chat request. Tries models in priority order, falling back
        automatically on failure or timeout.

        Returns:
            {
                "content": str,
                "model_used": str,
                "model_display": str,
                "reasoning": str | None,
                "attempts": int,
            }
        """
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        candidates = self._get_candidates(require_json=require_json)
        if not candidates:
            raise RuntimeError("No LLM models are currently available — all circuits open.")

        last_error: Exception | None = None
        for attempt, health in enumerate(candidates, start=1):
            cfg = health.config
            logger.info(
                "LLM attempt %d/%d — trying %s",
                attempt, len(candidates), cfg.display_name,
            )
            try:
                result = await self._call_model(
                    cfg=cfg,
                    messages=full_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    use_reasoning=use_reasoning and cfg.supports_reasoning,
                )
                health.record_success()
                result["attempts"] = attempt
                logger.info("LLM success on attempt %d (%s)", attempt, cfg.display_name)
                return result

            except Exception as exc:
                logger.warning(
                    "LLM %s failed (attempt %d): %s", cfg.display_name, attempt, exc
                )
                health.record_failure()
                last_error = exc
                continue

        raise RuntimeError(
            f"All {len(candidates)} LLM models failed. Last error: {last_error}"
        )

    async def health_status(self) -> list[dict]:
        """Return health snapshot of all models (for /api/llm/health endpoint)."""
        return [
            {
                "model_id": h.config.model_id,
                "display_name": h.config.display_name,
                "tier": h.config.tier.value,
                "available": h.is_available,
                "failures": h.failures,
                "success_rate": round(h.success_rate, 3),
                "total_requests": h.total_requests,
                "cooldown_s": COOLDOWN_S,
            }
            for h in self._health.values()
        ]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_candidates(self, require_json: bool = False) -> list[ModelHealth]:
        candidates = [
            h for h in self._health.values()
            if h.is_available
            and h.config.tier == ModelTier.FREE_OSS
            and (not require_json or h.config.supports_json)
        ]
        return sorted(candidates, key=lambda h: h.config.priority)

    async def _call_model(
        self,
        cfg: ModelConfig,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        use_reasoning: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": cfg.model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if use_reasoning and cfg.supports_reasoning:
            payload["reasoning"] = {"enabled": True}

        async with httpx.AsyncClient(timeout=cfg.timeout_s) as client:
            response = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://maniquantai.vercel.app",
                    "X-Title": "ManiQuantAI",
                },
                json=payload,
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"OpenRouter HTTP {response.status_code}: {response.text[:300]}"
            )

        data = response.json()

        # Handle OpenRouter error responses (HTTP 200 but error body)
        if "error" in data:
            raise RuntimeError(f"OpenRouter error: {data['error']}")

        choice = data["choices"][0]["message"]
        content = choice.get("content") or ""
        reasoning = None
        if use_reasoning:
            rd = choice.get("reasoning_details") or []
            reasoning = "\n".join(
                r.get("thinking", "") for r in rd if isinstance(r, dict)
            ) or None

        return {
            "content": content,
            "model_used": cfg.model_id,
            "model_display": cfg.display_name,
            "reasoning": reasoning,
        }


# ---------------------------------------------------------------------------
# Singleton instance — import this everywhere
# ---------------------------------------------------------------------------
router = LLMRouter()
