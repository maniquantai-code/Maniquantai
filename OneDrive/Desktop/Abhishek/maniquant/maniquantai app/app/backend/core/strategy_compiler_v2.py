"""ManiQuantAI Strategy Compiler v2

Extends the original compiler to handle a much wider range of crypto strategies:
  - EMA crossover (9/21, 20/50, 50/200)
  - MACD (12/26/9)
  - RSI + Bollinger (original)
  - Breakout / support-resistance
  - Scalping (fast EMA + tight stops)
  - Multi-symbol: any MT5 forex or crypto pair
  - Automatic agent team selection based on strategy type

The LLM is used for intent extraction only. All parameter normalization
and validation is deterministic Python — no LLM-invented values reach execution.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Symbol normalisation
# ─────────────────────────────────────────────────────────────────────────────

CRYPTO_MAP = {
    "btcusd": "BTCUSD", "btc/usd": "BTCUSD", "bitcoin": "BTCUSD", "btc": "BTCUSD",
    "ethusd": "ETHUSD", "eth/usd": "ETHUSD", "ethereum": "ETHUSD", "eth": "ETHUSD",
    "bnbusd": "BNBUSD", "bnb/usd": "BNBUSD", "binance coin": "BNBUSD",
    "solusd": "SOLUSD", "sol/usd": "SOLUSD", "solana": "SOLUSD", "sol": "SOLUSD",
    "xrpusd": "XRPUSD", "xrp/usd": "XRPUSD", "ripple": "XRPUSD", "xrp": "XRPUSD",
    "adausd": "ADAUSD", "ada/usd": "ADAUSD", "cardano": "ADAUSD", "ada": "ADAUSD",
    "dotusd": "DOTUSD", "dot/usd": "DOTUSD", "polkadot": "DOTUSD",
    "dogeusd": "DOGEUSD", "doge/usd": "DOGEUSD", "dogecoin": "DOGEUSD",
    "ltcusd": "LTCUSD", "ltc/usd": "LTCUSD", "litecoin": "LTCUSD",
    "avaxusd": "AVAXUSD", "avax/usd": "AVAXUSD", "avalanche": "AVAXUSD",
    "linkusd": "LINKUSD", "link/usd": "LINKUSD", "chainlink": "LINKUSD",
    "maticusd": "MATICUSD", "matic/usd": "MATICUSD", "polygon": "MATICUSD",
    "uniusd": "UNIUSD", "uni/usd": "UNIUSD", "uniswap": "UNIUSD",
    "eurusd": "EURUSD", "eur/usd": "EURUSD",
    "gbpusd": "GBPUSD", "gbp/usd": "GBPUSD",
    "usdjpy": "USDJPY", "usd/jpy": "USDJPY",
    "xauusd": "XAUUSD", "xau/usd": "XAUUSD", "gold": "XAUUSD",
    "xagusd": "XAGUSD", "silver": "XAGUSD",
    "us30":  "US30",   "dow jones": "US30",
    "nas100": "NAS100", "nasdaq": "NAS100",
    "sp500": "SP500",  "s&p": "SP500",
}

TF_MAP = {
    "1m": "1m", "1 min": "1m", "1min": "1m", "1 minute": "1m",
    "5m": "5m", "5 min": "5m", "5min": "5m", "5 minute": "5m",
    "15m": "15m", "15 min": "15m", "15min": "15m", "15 minute": "15m",
    "30m": "30m", "30 min": "30m", "30min": "30m", "30 minute": "30m",
    "1h": "1h", "1 hour": "1h", "1hr": "1h", "hourly": "1h",
    "4h": "4h", "4 hour": "4h", "4hr": "4h",
    "1d": "1d", "daily": "1d", "1 day": "1d",
}

STRATEGY_TYPES = {
    "ema_crossover":  {"agents": ["momentum", "sentiment"], "requires_vol": False},
    "rsi_bollinger":  {"agents": ["mean_reversion", "sentiment"], "requires_vol": False},
    "macd":           {"agents": ["momentum", "mean_reversion"], "requires_vol": False},
    "breakout":       {"agents": ["breakout", "momentum"], "requires_vol": True},
    "scalping":       {"agents": ["scalper", "momentum"], "requires_vol": False},
    "multi_signal":   {"agents": ["momentum", "mean_reversion", "breakout", "scalper", "sentiment"], "requires_vol": False},
    "custom":         {"agents": ["momentum", "mean_reversion", "breakout", "sentiment"], "requires_vol": False},
}


def _normalize_symbol(text: str) -> str:
    t = text.lower().strip()
    for k, v in CRYPTO_MAP.items():
        if k in t:
            return v
    m = re.search(r"\b([A-Z]{2,6})\s*/?USD\b", text, re.IGNORECASE)
    if m:
        return m.group(1).upper() + "USD"
    return "BTCUSD"


def _normalize_tf(text: str) -> str:
    t = text.lower()
    for k, v in TF_MAP.items():
        if k in t:
            return v
    if re.search(r"15\s*[-]?\s*(min|m)\b", t): return "15m"
    if re.search(r"4\s*[-]?\s*h",           t): return "4h"
    if re.search(r"1\s*[-]?\s*h",            t): return "1h"
    return "15m"


def _detect_strategy_type(text: str) -> str:
    t = text.lower()
    has_ema    = bool(re.search(r"\bema\b|\bexponential\b", t))
    has_rsi    = "rsi" in t
    has_bb     = "bollinger" in t or "bb(" in t
    has_macd   = "macd" in t
    has_break  = "breakout" in t or "break out" in t or "support" in t or "resistance" in t
    has_scalp  = "scalp" in t or "1m" in t or "1 min" in t or "5m" in t
    has_cross  = "cross" in t or "crossover" in t

    if has_scalp:             return "scalping"
    if has_break:             return "breakout"
    if has_macd:              return "macd"
    if has_ema and has_cross: return "ema_crossover"
    if has_rsi and has_bb:    return "rsi_bollinger"
    if has_rsi or has_ema:    return "multi_signal"
    return "multi_signal"   # default: use all agents


def _num(text: str, pattern: str, default: float) -> float:
    m = re.search(pattern, text, re.IGNORECASE)
    return float(m.group(1)) if m else default


def compile_strategy_v2(user_prompt: str) -> dict[str, Any]:
    """Deterministic strategy compilation — no LLM required for common patterns."""
    text = user_prompt.strip()
    lower = text.lower()

    symbol   = _normalize_symbol(text)
    tf       = _normalize_tf(text)
    stype    = _detect_strategy_type(text)
    agents   = STRATEGY_TYPES.get(stype, STRATEGY_TYPES["custom"])["agents"]

    lookback = int(_num(lower, r"(\d+)\s*days?", 90))
    risk_pct = _num(lower, r"risk\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*%", 1.0)
    risk_pct = min(risk_pct, 2.0)   # hard cap

    # EMA periods
    ema_periods = [int(x) for x in re.findall(r"\bema\s*\(?(\d+)\)?", lower)]
    if not ema_periods:
        ema_periods = [int(x) for x in re.findall(r"(\d+)\s*[-/]\s*(\d+)\s*(?:ema|crossover)", lower)]
        ema_periods = list({int(x) for x in ema_periods})
    ema_fast = ema_periods[0] if len(ema_periods) >= 1 else 9
    ema_slow = ema_periods[1] if len(ema_periods) >= 2 else 21

    # RSI
    rsi_period     = int(_num(lower, r"rsi\s*\(?(\d+)\)?", 14))
    rsi_entry_below = _num(lower, r"rsi.{0,60}(?:below|under|<)\s*(\d+(?:\.\d+)?)", 30.0)
    rsi_entry_above = _num(lower, r"rsi.{0,60}(?:above|over|>)\s*(\d+(?:\.\d+)?)", 70.0)
    rsi_exit_above  = _num(lower, r"(?:exit|close).{0,40}rsi.{0,20}(\d+(?:\.\d+)?)", 55.0)

    # Bollinger
    bb_period = int(_num(lower, r"bollinger.{0,30}(\d+)", 20))
    bb_std    = _num(lower, r"bollinger.{0,50}(\d+(?:\.\d+)?)\s*(?:std|standard|sigma|σ)", 2.0)

    # Stop loss
    atr_mult_sl = _num(lower, r"(?:stop.{0,20})(\d+(?:\.\d+)?)\s*[x×]\s*atr", 1.5)
    sl_pct      = _num(lower, r"stop.{0,20}(\d+(?:\.\d+)?)\s*%", 0.0)
    if sl_pct > 0:
        stop_loss = {"type": "PERCENT", "value": sl_pct}
    elif atr_mult_sl != 1.5 or "atr" in lower:
        stop_loss = {"type": "ATR", "period": 14, "multiplier": atr_mult_sl}
    else:
        stop_loss = {"type": "ATR", "period": 14, "multiplier": 1.5}

    # Take profit
    tp_mult  = _num(lower, r"(?:take.profit|tp).{0,40}(\d+(?:\.\d+)?)\s*[rx×]", 2.0)
    tp_pct   = _num(lower, r"take.profit.{0,20}(\d+(?:\.\d+)?)\s*%", 0.0)
    if tp_pct > 0:
        take_profit = {"type": "PERCENT", "value": tp_pct}
    else:
        take_profit = {"type": "R_MULTIPLE", "multiple": tp_mult}

    # Direction
    direction = "BOTH"
    if any(w in lower for w in ["long only", "only buy", "buy only"]):  direction = "LONG"
    if any(w in lower for w in ["short only", "only sell", "sell only"]): direction = "SHORT"

    runtime = {
        "symbol":           symbol,
        "timeframe":        tf,
        "lookback_days":    lookback,
        "rsi_period":       rsi_period,
        "rsi_entry_below":  rsi_entry_below,
        "rsi_entry_above":  rsi_entry_above,
        "rsi_exit_above":   rsi_exit_above,
        "bollinger_period": bb_period,
        "bollinger_std":    bb_std,
        "ema_fast":         ema_fast,
        "ema_slow":         ema_slow,
        "risk_pct":         risk_pct,
        "max_hold_hours":   None,
        "stop_loss":        stop_loss,
        "take_profit":      take_profit,
        "max_open_positions": 1,
    }

    unresolved = []
    if risk_pct == 1.0 and "risk" not in lower:
        unresolved.append("risk_pct — defaulted to 1%")
    if stype == "custom":
        unresolved.append("strategy_type — could not identify specific indicators")

    return {
        "version":       "2.0",
        "symbol":        symbol,
        "timeframe":     tf,
        "direction":     direction,
        "strategy_type": stype,
        "active_agents": agents,
        "entry": {
            "conditions": _build_entry_conditions(stype, runtime),
            "order_type": "MARKET",
        },
        "exit": {
            "conditions": _build_exit_conditions(stype, runtime),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        },
        "risk": {
            "risk_pct_per_trade": risk_pct,
            "max_open_positions": 1,
            "daily_loss_limit_pct": 5.0,
        },
        "position": {
            "sizing": "risk_based",
            "max_open_positions": 1,
        },
        "runtime": runtime,
        "source": {"user_prompt": user_prompt},
        "unresolved": unresolved,
    }


def _build_entry_conditions(stype: str, r: dict) -> list[str]:
    if stype == "ema_crossover":
        return [f"EMA({r['ema_fast']}) crosses above EMA({r['ema_slow']})", "ADX > 20 (trend confirmed)"]
    if stype == "rsi_bollinger":
        return [f"RSI({r['rsi_period']}) < {r['rsi_entry_below']}", f"Price touches lower Bollinger Band ({r['bollinger_period']}, {r['bollinger_std']}σ)"]
    if stype == "macd":
        return ["MACD(12,26,9) signal line crossover", "Histogram turns positive"]
    if stype == "breakout":
        return ["Price closes above 20-bar resistance", "Volume > 1.5× 20-bar average"]
    if stype == "scalping":
        return [f"EMA(3) crosses EMA(8)", f"RSI(7) between 40-65 (no extreme)"]
    return [f"Agent team consensus ≥ 0.35", "≥ 2 agents agree on direction"]


def _build_exit_conditions(stype: str, r: dict) -> list[str]:
    sl = r["stop_loss"]
    tp = r["take_profit"]
    sl_str = f"ATR({sl.get('period',14)}) × {sl.get('multiplier',1.5)}" if sl.get("type") == "ATR" else f"{sl.get('value','?')}% stop"
    tp_str = f"{tp.get('multiple',2)}R take-profit" if tp.get("type") == "R_MULTIPLE" else f"{tp.get('value','?')}% take-profit"
    return [sl_str, tp_str, "Agent team signals close position"]
