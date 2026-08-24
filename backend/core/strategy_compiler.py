"""LLM -> deterministic ManiQuantAI strategy specification compiler."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .llm_router import router as llm_router

ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT / "prompts" / "system.md"
SCHEMA_PATH = ROOT / "strategy_spec_schema.json"


def _system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("Strategy compiler did not return JSON")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Strategy compiler returned a non-object")
    return value


def _validate(spec: dict[str, Any], prompt: str) -> dict[str, Any]:
    required = ("version", "symbol", "timeframe", "direction", "entry", "exit", "risk", "position", "source")
    missing = [key for key in required if key not in spec]
    if missing:
        raise ValueError(f"Compiled strategy is missing: {', '.join(missing)}")
    if spec.get("timeframe") not in {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "unresolved"}:
        raise ValueError("Compiled strategy contains an invalid timeframe")
    if not isinstance(spec.get("source"), dict):
        spec["source"] = {}
    spec["source"]["user_prompt"] = prompt
    return spec


async def compile_strategy(prompt: str) -> dict[str, Any]:
    """Compile natural language once; all execution remains deterministic."""
    if not prompt.strip():
        raise ValueError("Strategy prompt cannot be empty")
    schema = _schema()
    result = await llm_router.chat(
        messages=[{"role": "user", "content": "Compile this trading strategy into the ManiQuantAI strategy specification. Return JSON only. Do not invent unspecified values.\n\nUSER STRATEGY:\n" + prompt}],
        require_json=True,
        system_prompt=_system_prompt() + "\n\nJSON SCHEMA:\n" + json.dumps(schema, separators=(",", ":")),
        max_tokens=900,
        temperature=0.0,
    )
    spec = _validate(_extract_json(result["content"]), prompt)
    spec["compiler"] = {"model": result.get("model_used"), "attempts": result.get("attempts", 1)}
    return spec
