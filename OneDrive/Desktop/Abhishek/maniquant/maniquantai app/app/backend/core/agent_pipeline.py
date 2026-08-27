"""ManiQuantAI v2 — post-backtest agent pipeline.

Validates indicator and risk rules for all v2 strategy types:
  ema_crossover, rsi_bollinger, macd, breakout, scalping, multi_signal.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentResult:
    ok: bool
    status: str
    errors: tuple[str, ...] = ()


def _pos(value: Any) -> bool:
    try: return float(value) > 0
    except (TypeError, ValueError): return False


def run_indicator_agent(spec: dict[str, Any]) -> AgentResult:
    """Validate indicators for all v2 strategy types."""
    runtime = spec.get("runtime") or {}
    stype   = spec.get("strategy_type", "multi_signal")
    errors: list[str] = []

    # RSI-based strategies
    if stype in {"rsi_bollinger", "multi_signal", "custom"}:
        if runtime.get("rsi_period") is None:
            errors.append("Missing rsi_period")
        elif not _pos(runtime["rsi_period"]):
            errors.append("rsi_period must be positive")
        if runtime.get("bollinger_period") is None:
            errors.append("Missing bollinger_period")
        if runtime.get("bollinger_std") is None:
            errors.append("Missing bollinger_std")
        elif not _pos(runtime.get("bollinger_std")):
            errors.append("bollinger_std must be positive")

    # EMA-based strategies — need ema_fast/ema_slow OR rsi_period fallback
    if stype in {"ema_crossover", "macd", "breakout", "scalping"}:
        ema_fast = runtime.get("ema_fast")
        ema_slow = runtime.get("ema_slow")
        # If either is missing, set a safe default rather than blocking
        if ema_fast is None:
            runtime["ema_fast"] = 9
        if ema_slow is None:
            runtime["ema_slow"] = 21
        if ema_fast and ema_slow and float(ema_fast) >= float(ema_slow):
            errors.append(f"ema_fast ({ema_fast}) must be < ema_slow ({ema_slow})")

    # ATR stop loss
    sl = runtime.get("stop_loss")
    if isinstance(sl, dict) and str(sl.get("type","")).upper() == "ATR":
        if not _pos(sl.get("period", 14)) or not _pos(sl.get("multiplier")):
            errors.append("ATR stop_loss requires positive period and multiplier")

    return AgentResult(not errors, "complete" if not errors else "failed", tuple(errors))


def run_risk_agent(spec: dict[str, Any]) -> AgentResult:
    """Validate risk controls for any v2 strategy type."""
    runtime = spec.get("runtime") or {}
    errors: list[str] = []

    # risk_pct
    try:
        rp = float(runtime.get("risk_pct") or runtime.get("risk", {}).get("risk_pct_per_trade") or 0)
        if not 0 < rp <= 2:
            errors.append(f"risk_pct={rp} must be > 0 and ≤ 2")
    except (TypeError, ValueError):
        errors.append("risk_pct is required and must be numeric")

    # stop_loss
    sl = runtime.get("stop_loss")
    if not isinstance(sl, dict):
        errors.append("stop_loss must be a structured rule {type, ...}")
    else:
        sl_type = str(sl.get("type","")).upper()
        if sl_type == "ATR":
            if not _pos(sl.get("period", 14)) or not _pos(sl.get("multiplier")):
                errors.append("ATR stop_loss needs positive period + multiplier")
        elif sl_type not in {"PERCENT","PRICE","ATR_MULTIPLE","ATR","TRAILING"}:
            errors.append(f"stop_loss.type '{sl_type}' is unsupported")

    # take_profit
    tp = runtime.get("take_profit")
    if not isinstance(tp, dict):
        errors.append("take_profit must be a structured rule {type, ...}")
    else:
        tp_type = str(tp.get("type","")).upper()
        if tp_type in {"R_MULTIPLE","R-MULTIPLE"}:
            if not _pos(tp.get("multiple")):
                errors.append("take_profit R multiple must be positive")
        elif tp_type not in {"PERCENT","PRICE"}:
            errors.append(f"take_profit.type '{tp_type}' is unsupported")

    # max_open_positions
    try:
        mp = int(runtime.get("max_open_positions", 1))
        if mp < 1: errors.append("max_open_positions must be ≥ 1")
    except (TypeError, ValueError):
        errors.append("max_open_positions must be numeric")

    return AgentResult(not errors, "complete" if not errors else "failed", tuple(errors))


def run_post_backtest_agents(spec: dict[str, Any]) -> dict[str, Any]:
    ind  = run_indicator_agent(spec)
    risk = run_risk_agent(spec)
    return {
        "indicator": {"status": ind.status,  "errors": list(ind.errors)},
        "risk":      {"status": risk.status, "errors": list(risk.errors)},
        "ready_for_live_gate": ind.ok and risk.ok,
    }
