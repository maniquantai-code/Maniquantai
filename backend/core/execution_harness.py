"""Deterministic security boundary for ManiQuantAI live execution.

The LLM/agent layer can propose a decision; this harness is the final gate.
It is intentionally small, deterministic, and independent of model output.
No live order may be queued unless every hard gate passes.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import time
from dataclasses import dataclass
from typing import Any

MAX_RISK_PCT = float(os.getenv("HARNESS_MAX_RISK_PCT", "2.0"))
MAX_BAR_COUNT = int(os.getenv("HARNESS_MAX_BAR_COUNT", "1000"))
MIN_BAR_COUNT = int(os.getenv("HARNESS_MIN_BAR_COUNT", "30"))
MAX_ORDER_VOLUME = float(os.getenv("HARNESS_MAX_ORDER_VOLUME", "100.0"))
MAX_REASON_LEN = 500

_ALLOWED_TIMEFRAMES = {"1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h", "2h", "4h", "1d"}
_SYMBOL_RE = re.compile(r"^[A-Z0-9._:/-]{1,32}$")


class HarnessReject(Exception):
    """A deterministic execution-gate rejection."""


@dataclass(frozen=True)
class HarnessResult:
    allowed: bool
    reason: str
    signal_key: str
    checks: tuple[str, ...]


def _fail(reason: str) -> None:
    raise HarnessReject(reason)


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        _fail(f"{name} is not numeric")
    if not math.isfinite(number):
        _fail(f"{name} is not finite")
    return number


def validate_execution_request(
    *,
    strategy: dict[str, Any],
    spec: dict[str, Any],
    result: dict[str, Any],
    symbol: str,
    timeframe: str,
    bars: list[dict[str, Any]],
    account_equity: float,
    current_position: str,
    bridge_online: bool,
    daily_pnl_pct: float | None = None,
    open_position_count: int = 0,
    kill_switch: bool = False,
) -> HarnessResult:
    """Apply hard safety gates before any broker/MT5 queue operation."""
    if kill_switch:
        _fail("Global execution kill switch is active")
    if not bridge_online:
        _fail("Execution bridge is offline")
    if not strategy.get("id") and not strategy.get("strategy_id"):
        _fail("Strategy identity is missing")
    if not bool(spec.get("live_approved")):
        _fail("Strategy is not live-approved")
    if spec.get("live_paused") or strategy.get("live_paused"):
        _fail("Strategy is paused")
    if spec.get("pipeline_stage") not in (None, "live_running", "live_approved", "live_ready", "awaiting_live_approval"):
        _fail("Strategy pipeline is not in a live execution state")

    symbol = symbol.strip().upper()
    if not _SYMBOL_RE.fullmatch(symbol):
        _fail("Invalid trading symbol")
    if timeframe not in _ALLOWED_TIMEFRAMES:
        _fail("Unsupported timeframe")
    if not (MIN_BAR_COUNT <= len(bars) <= MAX_BAR_COUNT):
        _fail("Bar count outside execution safety bounds")
    if current_position not in {"flat", "long", "short"}:
        _fail("Invalid current position")
    equity = _finite(account_equity, "account_equity")
    if equity <= 0:
        _fail("Account equity must be positive")

    if not bool(result.get("execute")):
        _fail("Portfolio Manager did not authorize execution")
    side = str(result.get("side") or "").lower()
    if side not in {"buy", "sell"}:
        _fail("Only buy/sell entries can reach the execution queue")
    if (current_position == "long" and side == "buy") or (current_position == "short" and side == "sell"):
        _fail("Duplicate directional position blocked")

    risk_pct = _finite(result.get("risk_pct", 0), "risk_pct")
    if risk_pct <= 0 or risk_pct > MAX_RISK_PCT:
        _fail("Risk-per-trade exceeds the hard execution cap")

    volume_pct = _finite(result.get("volume_pct", 0), "volume_pct")
    if volume_pct <= 0 or volume_pct > 1:
        _fail("Invalid position-size fraction")
    if open_position_count >= int(spec.get("max_open_positions", 1)):
        _fail("Maximum open positions reached")

    if daily_pnl_pct is not None:
        daily_limit = _finite(spec.get("daily_loss_limit_pct", -5.0), "daily_loss_limit_pct")
        # Strategy compiler historically stores this as a positive loss magnitude
        # (5.0), while execution_controls stores the threshold as -5.0.
        if daily_limit > 0:
            daily_limit = -daily_limit
        if daily_pnl_pct <= daily_limit:
            _fail("Daily loss limit reached")

    sl = result.get("stop_loss")
    tp = result.get("take_profit")
    if sl is None or tp is None:
        _fail("Stop-loss and take-profit are mandatory")
    sl = _finite(sl, "stop_loss")
    tp = _finite(tp, "take_profit")
    last_close = _finite(bars[-1].get("close"), "last_close")
    if last_close <= 0:
        _fail("Invalid market price")
    if side == "buy" and not (sl < last_close < tp):
        _fail("BUY protection levels are invalid")
    if side == "sell" and not (tp < last_close < sl):
        _fail("SELL protection levels are invalid")

    consensus = _finite(result.get("consensus", 0), "consensus")
    if abs(consensus) < 0.35:
        _fail("Consensus below execution threshold")

    signals = result.get("signals") or []
    agreeing = sum(1 for s in signals if isinstance(s, dict) and str(s.get("signal", "")).upper() == side.upper())
    if agreeing < 2:
        _fail("At least two independent deterministic agents must agree")

    reason = str(result.get("reason") or "").strip()
    if not reason or len(reason) > MAX_REASON_LEN:
        _fail("Execution reason is invalid")

    last_ts = str(bars[-1].get("ts", bars[-1].get("time", "")))
    if not last_ts:
        _fail("Market-data timestamp is missing")
    signal_key = hashlib.sha256(
        f"{strategy.get('id') or strategy.get('strategy_id')}|{symbol}|{timeframe}|{side}|{last_ts}".encode()
    ).hexdigest()

    return HarnessResult(
        allowed=True,
        reason="All deterministic execution gates passed",
        signal_key=signal_key,
        checks=(
            "kill_switch",
            "live_approval",
            "pipeline_state",
            "bridge_heartbeat",
            "market_data_bounds",
            "position_limit",
            "daily_loss_limit",
            "risk_cap",
            "protective_orders",
            "agent_consensus",
            "idempotency_key",
        ),
    )
