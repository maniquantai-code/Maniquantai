"""Production-safe LLM -> deterministic ManiQuantAI strategy compiler."""
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
    text = (text or "").strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    if start < 0:
        raise ValueError("MODEL_JSON_MISSING")
    depth = 0
    in_string = False
    escape = False
    end = -1
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        raise ValueError("MODEL_JSON_INCOMPLETE")
    value = json.loads(candidate[start:end])
    if not isinstance(value, dict):
        raise ValueError("MODEL_JSON_OBJECT_REQUIRED")
    return value


def _num(prompt: str, pattern: str, default: float) -> float:
    match = re.search(pattern, prompt, re.IGNORECASE)
    return float(match.group(1)) if match else default


def _deterministic_fallback(prompt: str) -> dict[str, Any] | None:
    """Compile common indicator/risk strategies without depending on an LLM.

    This is intentionally conservative: it only returns a spec when the prompt
    contains enough explicit information to execute deterministically.
    """
    p = prompt.lower()
    has_rsi = "rsi" in p
    has_bb = "bollinger" in p or "bb(" in p or "lower bollinger" in p or "upper bollinger" in p
    if not (has_rsi and has_bb):
        return None

    symbol = "BTCUSD" if "btcusd" in p.replace("/", "") or "btc/usd" in p or "bitcoin" in p else "BTCUSD"
    timeframe = "15m" if "15-minute" in p or "15 minute" in p or "15m" in p else "15m"
    rsi_period = int(_num(p, r"rsi\s*\(?\s*(\d+)\s*\)?", 14))
    bb_period = int(_num(p, r"bollinger[^\n]{0,30}?\(?\s*(\d+)\s*(?:,|\))", 20))
    bb_std = _num(p, r"bollinger[^\n]{0,40}?,\s*(\d+(?:\.\d+)?)", 2.0)
    risk_pct = _num(p, r"risk[^\n]{0,20}?(\d+(?:\.\d+)?)\s*%", 1.0)
    rsi_entry = _num(p, r"rsi[^\n]{0,35}?(?:below|under|<)\s*(\d+(?:\.\d+)?)", 30)
    rsi_exit = _num(p, r"(?:exit|reaches|above|>=)[^\n]{0,25}?rsi[^\n]{0,20}?(\d+(?:\.\d+)?)", 55)
    if rsi_exit == 55 and re.search(r"rsi\s*(?:reaches|>=|above)\s*(\d+)", p):
        rsi_exit = _num(p, r"rsi\s*(?:reaches|>=|above)\s*(\d+)", 55)
    atr_mult = _num(p, r"(?:atr|stop[- ]loss)[^\n]{0,45}?(\d+(?:\.\d+)?)\s*[×x]\s*atr", 1.5)
    tp_risk = _num(p, r"(?:take[- ]profit|profit)[^\n]{0,30}?(\d+(?:\.\d+)?)\s*[×x]\s*(?:initial )?risk", 2.0)

    return {
        "version": "1.0",
        "symbol": symbol,
        "timeframe": timeframe,
        "direction": "BOTH" if "short" in p else "LONG",
        "entry": {
            "all": [
                {"indicator": "RSI", "period": rsi_period, "operator": "<", "value": rsi_entry},
                {"indicator": "BOLLINGER_BAND", "band": "lower", "operator": "touch_or_below", "period": bb_period, "std": bb_std},
                {"confirmation": "candle_close"},
            ]
        },
        "exit": {"all": [{"indicator": "RSI", "operator": ">=", "value": rsi_exit}]},
        "risk": {"risk_pct": risk_pct, "max_open_positions": 1, "stop_loss": {"type": "ATR", "period": 14, "multiplier": atr_mult}, "take_profit": {"type": "R_MULTIPLE", "multiple": tp_risk}},
        "position": {"max_open_positions": 1},
        "runtime": {
            "symbol": symbol,
            "timeframe": timeframe,
            "lookback_days": 365,
            "rsi_period": rsi_period,
            "rsi_entry_below": rsi_entry,
            "rsi_exit_above": rsi_exit,
            "bollinger_period": bb_period,
            "bollinger_std": bb_std,
            "risk_pct": risk_pct,
            "max_hold_hours": 168,
            "stop_loss": {"type": "ATR", "period": 14, "multiplier": atr_mult},
            "take_profit": {"type": "R_MULTIPLE", "multiple": tp_risk},
        },
        "source": {"user_prompt": prompt},
        "unresolved": [],
    }


def _normalize(spec: dict[str, Any], prompt: str) -> dict[str, Any]:
    runtime = spec.setdefault("runtime", {})
    aliases = {"rsi": "rsi_period", "rsi_length": "rsi_period", "bb_period": "bollinger_period", "bollinger_length": "bollinger_period", "bb_std": "bollinger_std", "risk_percent": "risk_pct"}
    for source, target in aliases.items():
        if target not in runtime and source in runtime:
            runtime[target] = runtime[source]
    runtime.setdefault("symbol", spec.get("symbol"))
    runtime.setdefault("timeframe", spec.get("timeframe"))
    runtime.setdefault("lookback_days", 365)
    runtime.setdefault("max_hold_hours", 168)
    spec.setdefault("source", {})
    spec["source"]["user_prompt"] = prompt
    return spec


def _validate(spec: dict[str, Any], prompt: str) -> dict[str, Any]:
    required = ("version", "symbol", "timeframe", "direction", "entry", "exit", "risk", "position", "runtime", "source")
    missing = [key for key in required if key not in spec]
    if missing:
        raise ValueError(f"COMPILED_SPEC_MISSING:{','.join(missing)}")
    runtime = spec.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError("COMPILED_RUNTIME_INVALID")
    runtime_required = ("symbol", "timeframe", "lookback_days", "rsi_period", "rsi_entry_below", "rsi_exit_above", "bollinger_period", "bollinger_std", "risk_pct", "max_hold_hours", "stop_loss", "take_profit")
    missing_runtime = [key for key in runtime_required if key not in runtime]
    if missing_runtime:
        raise ValueError(f"COMPILED_RUNTIME_MISSING:{','.join(missing_runtime)}")
    if runtime.get("timeframe") not in {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "unresolved"}:
        raise ValueError("COMPILED_TIMEFRAME_INVALID")
    if float(runtime["risk_pct"]) <= 0 or float(runtime["risk_pct"]) > 5:
        raise ValueError("COMPILED_RISK_INVALID")
    spec["source"]["user_prompt"] = prompt
    return spec


async def compile_strategy(prompt: str) -> dict[str, Any]:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("STRATEGY_PROMPT_EMPTY")
    schema = _schema()
    system = _system_prompt() + "\n\nJSON SCHEMA:\n" + json.dumps(schema, separators=(",", ":"))
    errors: list[str] = []

    for attempt in range(1, 3):
        try:
            instruction = (
                "Compile this trading strategy into the ManiQuantAI strategy specification. "
                "Return JSON only. Do not invent unspecified values. Preserve explicit indicator, "
                "entry, exit, and risk rules. The output MUST contain every required runtime field.\n\nUSER STRATEGY:\n" + prompt
            )
            if attempt == 2:
                instruction = "Repair the following strategy compilation. Return ONLY valid JSON matching the schema. Keep all explicit rules unchanged.\n\n" + prompt
            result = await llm_router.chat(messages=[{"role": "user", "content": instruction}], require_json=True, system_prompt=system, max_tokens=1200, temperature=0.0)
            spec = _validate(_normalize(_extract_json(result.get("content", "")), prompt), prompt)
            spec["compiler"] = {"model": result.get("model_used"), "attempts": attempt, "recovered": attempt > 1}
            return spec
        except Exception as exc:
            errors.append(str(exc)[:180])

    fallback = _deterministic_fallback(prompt)
    if fallback is not None:
        spec = _validate(fallback, prompt)
        spec["compiler"] = {"model": "deterministic-fallback", "attempts": 2, "recovered": True}
        return spec

    raise ValueError("STRATEGY_COMPILATION_FAILED:" + " | ".join(errors[-2:]))
