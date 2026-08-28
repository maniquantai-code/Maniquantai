"""
Background health monitor for LLM models.
Pings each model every 60 seconds with a tiny probe message.
Marks models available/unavailable in the router's health table.
This runs as a background asyncio task so trading workflows never stop.
"""

from __future__ import annotations

import asyncio
import logging
import time

from .llm_router import router, MODEL_REGISTRY, OPENROUTER_KEY, OPENROUTER_URL

import httpx

logger = logging.getLogger("health_monitor")

PROBE_INTERVAL_S = 60       # check every 60 seconds
PROBE_MESSAGE    = [{"role": "user", "content": "ping"}]
PROBE_TIMEOUT_S  = 15       # fast probe — just checking connectivity


async def _probe_model(model_id: str) -> bool:
    """Returns True if model responds within timeout."""
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://maniquantai.vercel.app",
                    "X-Title": "ManiQuantAI-HealthProbe",
                },
                json={
                    "model": model_id,
                    "messages": PROBE_MESSAGE,
                    "max_tokens": 5,
                },
            )
        if resp.status_code != 200:
            return False
        data = resp.json()
        return "error" not in data
    except Exception as exc:
        logger.debug("Probe failed for %s: %s", model_id, exc)
        return False


async def run_health_monitor():
    """
    Infinite loop that probes every model periodically.
    Import and launch as an asyncio background task in main.py:

        asyncio.create_task(run_health_monitor())
    """
    logger.info("Health monitor started — probing %d models every %ds",
                len(MODEL_REGISTRY), PROBE_INTERVAL_S)

    while True:
        for cfg in MODEL_REGISTRY:
            health = router._health.get(cfg.model_id)
            if health is None:
                continue

            ok = await _probe_model(cfg.model_id)
            if ok:
                if health.failures > 0:
                    logger.info("Model RECOVERED: %s", cfg.display_name)
                health.failures = 0
            else:
                health.failures = min(health.failures + 1, 3)
                health.last_failure_ts = time.time()
                logger.warning(
                    "Model UNHEALTHY (%d/3 failures): %s",
                    health.failures, cfg.display_name,
                )

            # Small gap between probes to avoid hammering the API
            await asyncio.sleep(2)

        await asyncio.sleep(PROBE_INTERVAL_S)
