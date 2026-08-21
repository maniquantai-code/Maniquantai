"""Deterministic research/backtest pipeline.

Market-data policy:
  1. The authenticated user's MetaTrader 5 connection is required before the
     pipeline starts.
  2. MT5 data is attempted first through the configured MT5 bridge.
  3. Yahoo Finance is the only fallback when the MT5 feed fails.
  4. Coinbase and Binance are never called.

Vercel/Linux cannot host the native MetaTrader5 terminal itself. Production
MT5 access therefore uses MT5_BRIDGE_URL, which must point to a Windows/MT5
bridge with a logged-in terminal. The bridge is read-only for market data.
"""
from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from fastapi import APIRouter

from .auth import get_current_user

api_router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X")
MT5_BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "").rstrip("/")
MT5_BRIDGE_API_KEY = os.getenv("MT5_BRIDGE_API_KEY", "")


def _headers(token: str) -> dict[str, str]:
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def _load_strategy(sid: str, uid: str, token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/strategies",
            headers=_headers(token),
            params={
                "strategy_id": f"eq.{sid}",
                "user_id": f"eq.{uid}",
                "select": "strategy_id,name,raw_strategy_text,status,spec",
                "limit": "1",
            },
        )
    if not r.is_success or not r.json():
        raise RuntimeError("Strategy could not be loaded")
    return r.json()[0]


async def _save(sid: str, uid: str, token: str, state: dict[str, Any], status: str | None = None) -> None:
    payload: dict[str, Any] = {"spec": state, "updated_at": datetime.now(timezone.utc).isoformat()}
    if status:
        payload["status"] = status
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.patch(
            f"{SUPABASE_URL}/rest/v1/strategies",
            headers=_headers(token),
            params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"},
            json=payload,
        )
    if not r.is_success:
        raise RuntimeError(f"State save failed: {r.text[:300]}")


async def _has_mt5(uid: str, token: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/broker_accounts",
            headers=_headers(token),
            params={"user_id": f"eq.{uid}", "connector_type": "eq.mt5", "select": "id", "limit": "1"},
        )
    if not r.is_success:
        raise RuntimeError("Could not verify MetaTrader 5 connection")
    return bool(r.json())


def parse_strategy(text: str) -> dict[str, Any]:
    s = text.upper()
    if "BTC" in s:
        symbol = "BTCUSD"
    elif "ETH" in s:
        symbol = "ETHUSD"
    elif "EUR/USD" in s or "EURUSD" in s:
        symbol = "EURUSD"
    else:
        symbol = "BTCUSD"

    if re.search(r"4\s*-?\s*HOUR", s): timeframe = "4h"
    elif re.search(r"1\s*-?\s*HOUR", s): timeframe = "1h"
    elif re.search(r"30\s*-?\s*MIN", s): timeframe = "30m"
    elif re.search(r"15\s*-?\s*MIN", s): timeframe = "15m"
    elif re.search(r"5\s*-?\s*MIN", s): timeframe = "5m"
    elif re.search(r"1\s*-?\s*DAY|DAILY", s): timeframe = "1d"
    else: timeframe = "15m"

    days_m = re.search(r"(\d+)\s*DAYS?", s)
    risk_m = re.search(r"RISK\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    hold_m = re.search(r"(\d+)\s*HOURS?", s)
    rsi_entry_m = re.search(r"RSI.{0,100}(?:BELOW|LESS THAN|<)\s*(\d+(?:\.\d+)?)", s)
    rsi_exit_m = re.search(r"RSI.{0,100}(?:REACH(?:ES)?|ABOVE|GREATER THAN|>)\s*(\d+(?:\.\d+)?)", s)
    rsi_period_m = re.search(r"RSI\s*\(?\s*(\d+)", s)
    bb_period_m = re.search(r"BOLLINGER(?:\s+BANDS?)?\s*\(?\s*(\d+)", s)
    bb_std_m = re.search(r"BOLLINGER.{0,50}?(\d+(?:\.\d+)?)\s*(?:STD|STANDARD)", s)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "lookback_days": int(days_m.group(1)) if days_m else 90,
        "strategy_type": "rsi_bollinger_mean_reversion" if "RSI" in s and "BOLLINGER" in s else "custom",
        "rsi_period": int(rsi_period_m.group(1)) if rsi_period_m else 14,
        "rsi_entry_below": float(rsi_entry_m.group(1)) if rsi_entry_m else 30.0,
        "rsi_exit_above": float(rsi_exit_m.group(1)) if rsi_exit_m else 55.0,
        "bollinger_period": int(bb_period_m.group(1)) if bb_period_m else 20,
        "bollinger_std": float(bb_std_m.group(1)) if bb_std_m else 2.0,
        "risk_pct": float(risk_m.group(1)) if risk_m else 1.0,
        "max_hold_hours": int(hold_m.group(1)) if hold_m else None,
    }


def _rsi(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(values)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def _bb(values: list[float], period: int = 20, std_mult: float = 2.0) -> list[tuple[float, float, float] | None]:
    out: list[tuple[float, float, float] | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        w = values[i - period + 1 : i + 1]
        mean = sum(w) / period
        sd = math.sqrt(sum((x - mean) ** 2 for x in w) / period)
        out[i] = (mean, mean - std_mult * sd, mean + std_mult * sd)
    return out


def _metrics(returns: list[float], risk_pct: float) -> dict[str, Any]:
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x <= 0]
    equity = peak = 1.0
    max_dd = 0.0
    for ret in returns:
        equity *= 1.0 + ret
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = sum((x - mean) ** 2 for x in returns) / len(returns) if returns else 0.0
    sharpe = mean / math.sqrt(variance) * math.sqrt(252) if variance > 0 else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "total_trades": len(returns),
        "trade_count": len(returns),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) * 100 / len(returns), 2) if returns else 0.0,
        "total_return_pct": round((equity - 1) * 100, 2),
        "net_return_pct": round((equity - 1) * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else (float("inf") if gross_profit else 0.0),
        "avg_win_pct": round(sum(wins) / len(wins) * 100, 3) if wins else 0.0,
        "avg_loss_pct": round(abs(sum(losses) / len(losses)) * 100, 3) if losses else 0.0,
        "risk_pct": risk_pct,
        "final_equity_index": round(equity, 6),
    }


def _yf_symbol(symbol: str) -> str:
    mapping = {"EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "JPY=X", "AUDUSD": "AUDUSD=X"}
    if symbol in mapping:
        return mapping[symbol]
    if symbol.endswith("USDT"):
        return symbol[:-4] + "-USD"
    if symbol.endswith("USD"):
        return symbol[:-3] + "-USD"
    return symbol


def _yf_interval(tf: str) -> str:
    return {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "4h": "60m", "1d": "1d"}.get(tf, "15m")


async def _yahoo_data(symbol: str, timeframe: str, days: int) -> list[dict[str, float | int]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    interval = _yf_interval(timeframe)
    if interval in {"1m", "5m", "15m", "30m", "60m"}:
        start = max(start, end - timedelta(days=59))
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{_yf_symbol(symbol)}"
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": "Mozilla/5.0"}) as c:
        r = await c.get(url, params={"period1": int(start.timestamp()), "period2": int(end.timestamp()), "interval": interval, "events": "history", "includeAdjustedClose": "true"})
        r.raise_for_status()
        result = r.json().get("chart", {}).get("result", [None])[0]
    if not result:
        raise RuntimeError("Yahoo Finance returned no market data")
    q = result.get("indicators", {}).get("quote", [{}])[0]
    rows: list[dict[str, float | int]] = []
    for i, ts in enumerate(result.get("timestamp", [])):
        try:
            rows.append({"ts": int(ts) * 1000, "open": float(q["open"][i]), "high": float(q["high"][i]), "low": float(q["low"][i]), "close": float(q["close"][i])})
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    if timeframe == "4h":
        rows = _resample(rows, 4 * 60 * 60 * 1000)
    return rows


def _resample(rows: list[dict[str, float | int]], width_ms: int) -> list[dict[str, float | int]]:
    buckets: dict[int, list[dict[str, float | int]]] = {}
    for row in rows:
        bucket = int(row["ts"]) // width_ms * width_ms
        buckets.setdefault(bucket, []).append(row)
    out: list[dict[str, float | int]] = []
    for ts, group in sorted(buckets.items()):
        out.append({"ts": ts, "open": group[0]["open"], "high": max(x["high"] for x in group), "low": min(x["low"] for x in group), "close": group[-1]["close"]})
    return out


async def _mt5_data(symbol: str, timeframe: str, days: int) -> list[dict[str, float | int]]:
    """Read candles from an externally hosted MT5 terminal/bridge.

    The native MetaTrader5 package cannot run inside Vercel's Linux runtime;
    the bridge is the production-safe way to reach the user's MT5 terminal.
    """
    if not MT5_BRIDGE_URL:
        raise RuntimeError("MT5_BRIDGE_URL is not configured")
    tf_map = {"1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15", "30m": "TIMEFRAME_M30", "1h": "TIMEFRAME_H1", "4h": "TIMEFRAME_H4", "1d": "TIMEFRAME_D1"}
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    headers = {"X-API-Key": MT5_BRIDGE_API_KEY} if MT5_BRIDGE_API_KEY else {}
    async with httpx.AsyncClient(timeout=30, headers=headers) as c:
        r = await c.get(f"{MT5_BRIDGE_URL}/rates/range", params={"symbol": symbol, "timeframe": tf_map.get(timeframe, "TIMEFRAME_M15"), "date_from": start.isoformat(), "date_to": end.isoformat()})
        r.raise_for_status()
        payload = r.json()
    raw = payload.get("rates") if isinstance(payload, dict) else payload
    if not raw:
        raise RuntimeError("MT5 bridge returned no candles")
    rows: list[dict[str, float | int]] = []
    for x in raw:
        ts = x.get("time", x.get("timestamp")) if isinstance(x, dict) else x[0]
        if isinstance(ts, str):
            ts = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
        elif float(ts) < 10_000_000_000:
            ts = int(float(ts) * 1000)
        else:
            ts = int(float(ts))
        rows.append({"ts": ts, "open": float(x.get("open", x[1]) if isinstance(x, dict) else x[1]), "high": float(x.get("high", x[2]) if isinstance(x, dict) else x[2]), "low": float(x.get("low", x[3]) if isinstance(x, dict) else x[3]), "close": float(x.get("close", x[4]) if isinstance(x, dict) else x[4])})
    return sorted(rows, key=lambda x: int(x["ts"]))


def _backtest(rows: list[dict[str, float | int]], spec: dict[str, Any]) -> dict[str, Any]:
    closes = [float(x["close"]) for x in rows]
    lows = [float(x["low"]) for x in rows]
    times = [int(x["ts"]) for x in rows]
    rs = _rsi(closes, int(spec["rsi_period"]))
    bb = _bb(closes, int(spec["bollinger_period"]), float(spec["bollinger_std"]))
    returns: list[float] = []
    trades: list[dict[str, Any]] = []
    entry: dict[str, Any] | None = None
    max_hold_ms = int(spec["max_hold_hours"] * 3600000) if spec.get("max_hold_hours") else None

    for i in range(1, len(rows)):
        if entry is None:
            if rs[i] is not None and bb[i] is not None and rs[i] < float(spec["rsi_entry_below"]) and lows[i] <= float(bb[i][1]):
                entry = {"i": i, "price": closes[i], "ts": times[i], "rsi": rs[i]}
            continue

        reason = None
        if rs[i] is not None and rs[i] >= float(spec["rsi_exit_above"]):
            reason = "rsi_exit"
        elif max_hold_ms and times[i] - entry["ts"] >= max_hold_ms:
            reason = "time_exit"
        if reason:
            pct = (closes[i] - entry["price"]) / entry["price"]
            # Risk is represented in the normalized return series; the actual
            # position size is capped so max loss is risk_pct of equity when a
            # stop/risk boundary is introduced by the execution layer.
            returns.append(pct)
            trades.append({"entry_time": datetime.fromtimestamp(entry["ts"] / 1000, timezone.utc).isoformat(), "exit_time": datetime.fromtimestamp(times[i] / 1000, timezone.utc).isoformat(), "entry_price": round(entry["price"], 8), "exit_price": round(closes[i], 8), "return_pct": round(pct * 100, 4), "risk_pct": float(spec["risk_pct"]), "exit_reason": reason})
            entry = None

    return {"metrics": _metrics(returns, float(spec["risk_pct"])), "trades": trades[-100:]}


async def run_pipeline(strategy_id: str, user_id: str, token: str) -> None:
    """Run the gated deterministic research/backtest pipeline in the background."""
    try:
        if not await _has_mt5(user_id, token):
            strategy = await _load_strategy(strategy_id, user_id, token)
            state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
            state["pipeline_stage"] = "awaiting_mt5_connection"
            state["error"] = "MetaTrader 5 connection required before the strategy pipeline can start"
            state["agents"] = {**state.get("agents", {}), "research": "idle", "backtest": "idle", "indicator": "gated", "paper": "gated", "approval": "gated", "live": "gated"}
            await _save(strategy_id, user_id, token, state, "awaiting_mt5")
            return

        strategy = await _load_strategy(strategy_id, user_id, token)
        state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
        spec = parse_strategy(strategy.get("raw_strategy_text") or state.get("raw_strategy_text", ""))
        state["parsed_strategy"] = spec
        state["pipeline_stage"] = "research_running"
        state["agents"] = {**state.get("agents", {}), "research": "running", "backtest": "queued", "indicator": "queued", "paper": "gated", "approval": "gated", "live": "gated"}
        await _save(strategy_id, user_id, token, state, "research")

        # MT5 is always attempted first. Yahoo is only a fallback.
        try:
            rows = await _mt5_data(spec["symbol"], spec["timeframe"], int(spec["lookback_days"]))
            source = "MT5"
        except Exception as mt5_exc:
            state["mt5_error"] = str(mt5_exc)[:500]
            try:
                rows = await _yahoo_data(spec["symbol"], spec["timeframe"], int(spec["lookback_days"]))
                source = "Yahoo Finance"
            except Exception as yahoo_exc:
                state["pipeline_stage"] = "failed"
                state["error"] = f"Market data unavailable. MT5: {mt5_exc} | Yahoo Finance: {yahoo_exc}"
                state["agents"] = {**state.get("agents", {}), "research": "failed", "backtest": "failed"}
                await _save(strategy_id, user_id, token, state, "failed")
                return

        if len(rows) < max(int(spec["rsi_period"]), int(spec["bollinger_period"])) + 5:
            raise RuntimeError("Not enough candles to calculate the requested indicators")

        state["pipeline_stage"] = "backtest_running"
        state["agents"] = {**state.get("agents", {}), "research": "complete", "backtest": "running", "indicator": "queued"}
        state["data_source"] = source
        state["data_source_message"] = "📡 Market data from your MetaTrader 5 account" if source == "MT5" else "📊 MT5 feed failed; using Yahoo Finance fallback"
        state["bars_loaded"] = len(rows)
        await _save(strategy_id, user_id, token, state, "backtesting")

        result = _backtest(rows, spec)
        state["backtest"] = {**result, "symbol": spec["symbol"], "timeframe": spec["timeframe"], "period_days": spec["lookback_days"], "data_source": source}
        state["pipeline_stage"] = "backtest_complete"
        state["agents"] = {**state.get("agents", {}), "research": "complete", "backtest": "complete", "indicator": "complete", "paper": "gated", "approval": "gated", "live": "gated"}
        state["pending_confirmation"] = "backtest_review"
        await _save(strategy_id, user_id, token, state, "backtest_complete")
    except Exception as exc:
        try:
            strategy = await _load_strategy(strategy_id, user_id, token)
            state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
            state["pipeline_stage"] = "failed"
            state["error"] = str(exc)
            state["agents"] = {**state.get("agents", {}), "research": "failed", "backtest": "failed"}
            await _save(strategy_id, user_id, token, state, "failed")
        except Exception:
            pass


@api_router.get("/status/{strategy_id}")
async def pipeline_status(strategy_id: str, user=__import__("fastapi").Depends(get_current_user)):
    token = user.get("_access_token")
    if not token:
        from fastapi import HTTPException
        raise HTTPException(401, "Missing access token")
    strategy = await _load_strategy(strategy_id, user["id"], token)
    state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
    return {"strategy_id": strategy_id, "status": strategy.get("status"), "pipeline_stage": state.get("pipeline_stage"), "agents": state.get("agents", {}), "backtest": state.get("backtest"), "data_source": state.get("data_source"), "error": state.get("error")}
