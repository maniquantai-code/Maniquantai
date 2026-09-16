"""Pure deterministic execution engine for compiled ManiQuantAI strategies.

This module intentionally has no LLM/network/MT5 dependencies.  It consumes a
validated Strategy Spec and OHLC bars and returns a small execution decision.
The bridge can therefore run continuously even when the LLM/provider is down.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence
import math


@dataclass(frozen=True)
class Signal:
    side: str  # buy, sell, close_buy, close_sell
    reason: str
    candle_time: int
    signal_key: str


def _closes(bars: Sequence[dict[str, Any]]) -> list[float]:
    return [float(b["close"]) for b in bars]


def _highs(bars: Sequence[dict[str, Any]]) -> list[float]:
    return [float(b["high"]) for b in bars]


def _lows(bars: Sequence[dict[str, Any]]) -> list[float]:
    return [float(b["low"]) for b in bars]


def ema(values: Sequence[float], period: int) -> list[float | None]:
    if period < 1:
        raise ValueError("EMA period must be positive")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    value = sum(values[:period]) / period
    out[period - 1] = value
    alpha = 2.0 / (period + 1)
    for i in range(period, len(values)):
        value = alpha * values[i] + (1.0 - alpha) * value
        out[i] = value
    return out


def rsi(values: Sequence[float], period: int) -> list[float | None]:
    if period < 1:
        raise ValueError("RSI period must be positive")
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(values)):
        if i > period:
            ag = (ag * (period - 1) + gains[i - 1]) / period
            al = (al * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def bollinger(values: Sequence[float], period: int, mult: float) -> list[tuple[float, float, float] | None]:
    if period < 1 or mult < 0:
        raise ValueError("Invalid Bollinger parameters")
    out: list[tuple[float, float, float] | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        mean = sum(window) / period
        sd = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
        out[i] = (mean, mean - mult * sd, mean + mult * sd)
    return out


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float | None], list[float | None]]:
    ef, es = ema(values, fast), ema(values, slow)
    line: list[float | None] = [None if ef[i] is None or es[i] is None else ef[i] - es[i] for i in range(len(values))]
    clean = [float(x) for x in line if x is not None]
    sig_clean = ema(clean, signal)
    sig: list[float | None] = [None] * len(values)
    j = 0
    for i, x in enumerate(line):
        if x is not None:
            sig[i] = sig_clean[j]
            j += 1
    return line, sig


def crossed_up(a: Sequence[float | None], b: Sequence[float | None], i: int) -> bool:
    return i > 0 and None not in (a[i], b[i], a[i - 1], b[i - 1]) and a[i] > b[i] and a[i - 1] <= b[i - 1]


def crossed_down(a: Sequence[float | None], b: Sequence[float | None], i: int) -> bool:
    return i > 0 and None not in (a[i], b[i], a[i - 1], b[i - 1]) and a[i] < b[i] and a[i - 1] >= b[i - 1]


def _runtime(spec: dict[str, Any]) -> dict[str, Any]:
    parsed = spec.get("parsed_strategy") or spec
    return parsed.get("runtime") or parsed


def _stype(spec: dict[str, Any]) -> str:
    parsed = spec.get("parsed_strategy") or spec
    return str(parsed.get("strategy_type") or spec.get("strategy_type") or "custom").lower()


def _direction(spec: dict[str, Any]) -> str:
    parsed = spec.get("parsed_strategy") or spec
    return str(parsed.get("direction") or "BOTH").upper()


def _conditions(spec: dict[str, Any]) -> dict[str, Any]:
    """Build a machine-readable plan from the canonical compiled fields.

    The compiler remains the source of normalized parameters; this function is
    deliberately deterministic and has no natural-language interpretation.
    """
    r = _runtime(spec)
    t = _stype(spec)
    if t == "ema_crossover":
        return {"kind": t, "fast": int(r.get("ema_fast", 9)), "slow": int(r.get("ema_slow", 21))}
    if t == "rsi_bollinger":
        return {
            "kind": t,
            "rsi_period": int(r.get("rsi_period", 14)),
            "entry_below": float(r.get("rsi_entry_below", 30)),
            "entry_above": float(r.get("rsi_entry_above", 70)),
            "exit_above": float(r.get("rsi_exit_above", 55)),
            "exit_below": float(r.get("rsi_exit_below", 45)),
            "bb_period": int(r.get("bollinger_period", 20)),
            "bb_std": float(r.get("bollinger_std", 2)),
        }
    if t == "macd":
        return {"kind": t, "fast": 12, "slow": 26, "signal": 9}
    if t == "breakout":
        return {"kind": t, "lookback": int(r.get("breakout_lookback", 20)), "volume_multiplier": float(r.get("breakout_volume_multiplier", 1.5))}
    if t == "scalping":
        return {"kind": t, "fast": 3, "slow": 8, "rsi_period": 7}
    raise ValueError(f"Unsupported strategy_type: {t}")


def build_execution_plan(spec: dict[str, Any]) -> dict[str, Any]:
    """Return an immutable-style, JSON-safe execution plan."""
    parsed = spec.get("parsed_strategy") or spec
    plan = _conditions(spec)
    return {
        "version": "1",
        "strategy_id": parsed.get("strategy_id") or spec.get("strategy_id"),
        "symbol": str(parsed.get("symbol") or _runtime(spec).get("symbol") or "").upper(),
        "timeframe": str(parsed.get("timeframe") or _runtime(spec).get("timeframe") or "15m"),
        "direction": _direction(spec),
        "max_open_positions": int((parsed.get("risk") or {}).get("max_open_positions", 1)),
        "conditions": plan,
    }


def evaluate_plan(plan: dict[str, Any], bars: Sequence[dict[str, Any]], idx: int, has_long: bool = False, has_short: bool = False) -> Signal | None:
    if idx < 1 or idx >= len(bars):
        return None
    c, h, l = _closes(bars), _highs(bars), _lows(bars)
    kind = str(plan["conditions"]["kind"])
    long_entry = short_entry = False
    reason = ""

    if kind == "ema_crossover":
        ef = ema(c, int(plan["conditions"]["fast"]))
        es = ema(c, int(plan["conditions"]["slow"]))
        long_entry, short_entry = crossed_up(ef, es, idx), crossed_down(ef, es, idx)
        reason = "EMA crossover"
    elif kind == "rsi_bollinger":
        q = plan["conditions"]
        rr = rsi(c, q["rsi_period"])
        bb = bollinger(c, q["bb_period"], q["bb_std"])
        if rr[idx] is None or bb[idx] is None:
            return None
        long_entry = rr[idx] < q["entry_below"] and l[idx] <= bb[idx][1]
        short_entry = rr[idx] > q["entry_above"] and h[idx] >= bb[idx][2]
        if has_long and rr[idx] >= q["exit_above"]:
            return Signal("close_buy", f"RSI {rr[idx]:.2f} exit", int(bars[idx]["time"]), f"{plan['strategy_id']}:{bars[idx]['time']}:close_buy")
        if has_short and rr[idx] <= q["exit_below"]:
            return Signal("close_sell", f"RSI {rr[idx]:.2f} exit", int(bars[idx]["time"]), f"{plan['strategy_id']}:{bars[idx]['time']}:close_sell")
        reason = f"RSI {rr[idx]:.2f} + Bollinger touch"
    elif kind == "macd":
        ml, sl = macd(c, plan["conditions"]["fast"], plan["conditions"]["slow"], plan["conditions"]["signal"])
        long_entry, short_entry = crossed_up(ml, sl, idx), crossed_down(ml, sl, idx)
        reason = "MACD signal crossover"
    elif kind == "breakout":
        n = plan["conditions"]["lookback"]
        if idx < n:
            return None
        resistance, support = max(h[idx - n:idx]), min(l[idx - n:idx])
        long_entry, short_entry = c[idx] > resistance, c[idx] < support
        reason = f"{n}-bar breakout"
    elif kind == "scalping":
        ef, es = ema(c, plan["conditions"]["fast"]), ema(c, plan["conditions"]["slow"])
        long_entry, short_entry = crossed_up(ef, es, idx), crossed_down(ef, es, idx)
        reason = "EMA(3)/EMA(8) crossover"

    direction = plan["direction"]
    if direction == "LONG":
        short_entry = False
    elif direction == "SHORT":
        long_entry = False
    if has_long or has_short or not (long_entry or short_entry):
        return None
    side = "buy" if long_entry else "sell"
    candle = int(bars[idx]["time"])
    return Signal(side, reason, candle, f"{plan['strategy_id']}:{candle}:{side}")
