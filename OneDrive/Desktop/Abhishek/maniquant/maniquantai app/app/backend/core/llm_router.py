"""
ManiQuantAI LLM Router
======================
Fast, resilient OpenRouter routing for interactive AI requests.
Credentials are read only from environment variables.

Performance policy:
- Prefer a fast non-thinking free model for interactive work.
- Route the selected model to the lowest-latency healthy provider.
- Reuse one HTTP client per backend process to avoid a new TLS connection per request.
- Fall back quickly when a model/provider is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger("llm_router")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()


class ModelTier(str, Enum):
    FREE_OSS = "free_oss"
    PAID = "paid"


@dataclass
class ModelConfig:
    model_id: str
    display_name: str
    tier: ModelTier
    supports_json: bool = True
    supports_reasoning: bool = False
    timeout_s: float = 25.0
    priority: int = 0


# Qwen3 Next Instruct is first for user-facing speed: it is non-thinking
# and is currently available as a free OpenRouter model. Other models are
# retained as fallbacks for resilience.
MODEL_REGISTRY: list[ModelConfig] = [
    ModelConfig("qwen/qwen3-next-80b-a3b-instruct:free", "Qwen3 Next 80B A3B", ModelTier.FREE_OSS, timeout_s=20.0, priority=0),
    ModelConfig("openai/gpt-oss-20b:free", "GPT-OSS 20B", ModelTier.FREE_OSS, supports_reasoning=True, timeout_s=20.0, priority=1),
    ModelConfig("nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron Ultra 550B", ModelTier.FREE_OSS, supports_reasoning=True, timeout_s=25.0, priority=2),
    ModelConfig("nvidia/nemotron-3.5-lightning:free", "Nemotron Lightning", ModelTier.FREE_OSS, supports_reasoning=True, timeout_s=20.0, priority=3),
    ModelConfig("google/gemma-4-26b-a4b-it:free", "Gemma 4 26B", ModelTier.FREE_OSS, timeout_s=20.0, priority=4),
]

COOLDOWN_S = 120


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
        if (time.time() - self.last_failure_ts) > COOLDOWN_S:
            self.failures = 0
        return self.failures < 3

    def record_success(self) -> None:
        self.failures = 0
        self.total_requests += 1
        self.total_successes += 1

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure_ts = time.time()
        self.total_requests += 1

    @property
    def success_rate(self) -> float:
        return self.total_successes / self.total_requests if self.total_requests else 1.0


class LLMRouter:
    def __init__(self) -> None:
        self._health = {
            m.model_id: ModelHealth(config=m)
            for m in sorted(MODEL_REGISTRY, key=lambda x: x.priority)
        }
        self._lock = asyncio.Lock()
        # Reuse connections across requests in a warm FastAPI/Vercel instance.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(25.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def chat(
        self,
        messages: list[dict],
        *,
        require_json: bool = False,
        system_prompt: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        use_reasoning: bool = False,
    ) -> dict[str, Any]:
        if not OPENROUTER_KEY:
            raise RuntimeError("OPENROUTER_API_KEY is not configured on the backend.")

        full_messages: list[dict] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        candidates = self._get_candidates(require_json=require_json)
        if not candidates:
            raise RuntimeError("No LLM models are currently available — all circuits are open.")

        last_error: Exception | None = None
        for attempt, health in enumerate(candidates, start=1):
            cfg = health.config
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
                return result
            except Exception as exc:
                logger.warning("LLM %s failed: %s", cfg.display_name, exc)
                health.record_failure()
                last_error = exc

        raise RuntimeError(f"All {len(candidates)} LLM models failed. Last error: {last_error}")

    async def stream_chat(
        self,
        messages: list[dict],
        *,
        require_json: bool = False,
        system_prompt: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream the first available model so the UI shows output immediately."""
        if not OPENROUTER_KEY:
            raise RuntimeError("OPENROUTER_API_KEY is not configured on the backend.")

        full_messages: list[dict] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        candidates = self._get_candidates(require_json=require_json)
        if not candidates:
            raise RuntimeError("No LLM models are currently available.")

        last_error: Exception | None = None
        for attempt, health in enumerate(candidates, start=1):
            cfg = health.config
            emitted = False
            try:
                async with self._client.stream(
                    "POST",
                    OPENROUTER_URL,
                    headers=self._headers(),
                    json={
                        "model": cfg.model_id,
                        "messages": full_messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "stream": True,
                        "provider": {"sort": "latency", "allow_fallbacks": True},
                    },
                    timeout=httpx.Timeout(cfg.timeout_s, connect=5.0),
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise RuntimeError(f"OpenRouter HTTP {response.status_code}: {body[:300]}")

                    async for line in response.aiter_lines():
                        if not line or line.startswith(":") or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except Exception:
                            continue
                        delta = event.get("choices", [{}])[0].get("delta", {}).get("content") or ""
                        if delta:
                            emitted = True
                            yield {
                                "type": "delta",
                                "content": delta,
                                "model_used": cfg.model_id,
                                "model_display": cfg.display_name,
                                "attempts": attempt,
                            }

                if not emitted:
                    raise RuntimeError("Model returned an empty streamed response.")
                health.record_success()
                yield {"type": "done", "model_used": cfg.model_id, "attempts": attempt}
                return
            except Exception as exc:
                logger.warning("Streaming LLM %s failed: %s", cfg.display_name, exc)
                health.record_failure()
                last_error = exc
                if emitted:
                    break

        raise RuntimeError(f"All streaming LLM models failed. Last error: {last_error}")

    async def health_status(self) -> list[dict]:
        configured = bool(OPENROUTER_KEY)
        return [
            {
                "model_id": h.config.model_id,
                "display_name": h.config.display_name,
                "tier": h.config.tier.value,
                "available": h.is_available and configured,
                "failures": h.failures,
                "success_rate": round(h.success_rate, 3),
                "total_requests": h.total_requests,
                "cooldown_s": COOLDOWN_S,
                "credentials_configured": configured,
            }
            for h in self._health.values()
        ]

    def _get_candidates(self, require_json: bool = False) -> list[ModelHealth]:
        return sorted(
            [
                h for h in self._health.values()
                if h.is_available
                and h.config.tier == ModelTier.FREE_OSS
                and (not require_json or h.config.supports_json)
            ],
            key=lambda h: h.config.priority,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://maniquantai-maniquant-ai.vercel.app",
            "X-Title": "ManiQuantAI",
        }

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
            "provider": {"sort": "latency", "allow_fallbacks": True},
        }
        if use_reasoning and cfg.supports_reasoning:
            payload["reasoning"] = {"enabled": True}

        response = await self._client.post(
            OPENROUTER_URL,
            headers=self._headers(),
            json=payload,
            timeout=httpx.Timeout(cfg.timeout_s, connect=5.0),
        )

        if response.status_code != 200:
            raise RuntimeError(f"OpenRouter HTTP {response.status_code}: {response.text[:300]}")

        data = response.json()
        if "error" in data:
            raise RuntimeError(f"OpenRouter error: {data['error']}")

        choice = data["choices"][0]["message"]
        content = choice.get("content") or ""
        reasoning = None
        if use_reasoning:
            details = choice.get("reasoning_details") or []
            reasoning = "\n".join(
                r.get("thinking", "") for r in details if isinstance(r, dict)
            ) or None

        return {
            "content": content,
            "model_used": cfg.model_id,
            "model_display": cfg.display_name,
            "reasoning": reasoning,
        }


router = LLMRouter()
