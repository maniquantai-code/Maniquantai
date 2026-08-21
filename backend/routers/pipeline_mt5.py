"""Deterministic strategy pipeline backed by the user's MT5 terminal bridge."""
from __future__ import annotations

import asyncio
import math
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from .auth import get_current_user

api_router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
SB = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
ANON = os.getenv("SUPABASE_ANON_KEY", "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X").strip()
SERVICE = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def h(token: str) -> dict[str, str]:
    return {"apikey": ANON, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}


def sh() -> dict[str, str]:
    if not SERVICE:
        raise RuntimeError("MT5 bridge service configuration is incomplete")
    return {"apikey": SERVICE, "Authorization": f"Bearer {SERVICE}", "Content-Type": "application/json", "Prefer": "return=representation"}


async def load(sid: str, uid: str, token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{SB}/rest/v1/strategies", headers=h(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}", "select": "strategy_id,name,raw_strategy_text,status,spec", "limit": "1"})
    if not r.is_success or not r.json():
        raise RuntimeError("Strategy could not be loaded")
    return r.json()[0]


async def save(sid: str, uid: str, token: str, state: dict[str, Any], status: str | None = None) -> None:
    payload = {"spec": state, "updated_at": datetime.now(timezone.utc).isoformat()}
    if status:
        payload["status"] = status
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.patch(f"{SB}/rest/v1/strategies", headers=h(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"}, json=payload)
    if not r.is_success:
        raise RuntimeError(f"Strategy state could not be saved: {r.text[:250]}")


async def connected(uid: str, token: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{SB}/rest/v1/broker_accounts", headers=h(token), params={"user_id": f"eq.{uid}", "connector_type": "eq.mt5", "select": "id", "limit": "1"})
    if not r.is_success:
        raise RuntimeError("Could not verify MT5 connection")
    return bool(r.json())


def parse(x: str) -> dict[str, Any]:
    s = x.upper()
    symbol = "BTCUSD" if "BTC" in s else "ETHUSD" if "ETH" in s else "EURUSD" if "EURUSD" in s or "EUR/USD" in s else "BTCUSD"
    tf = "4h" if re.search(r"4\s*-?\s*HOUR", s) else "1h" if re.search(r"1\s*-?\s*HOUR", s) else "30m" if re.search(r"30\s*-?\s*MIN", s) else "15m" if re.search(r"15\s*-?\s*MIN", s) else "5m" if re.search(r"5\s*-?\s*MIN", s) else "1d" if re.search(r"1\s*-?\s*DAY|DAILY", s) else "15m"

    def g(pattern: str, default: Any) -> Any:
        m = re.search(pattern, s)
        return m.group(1) if m else default

    return {
        "symbol": symbol,
        "timeframe": tf,
        "lookback_days": int(g(r"(\d+)\s*DAYS?", 90)),
        "rsi_period": int(g(r"RSI\s*\(?\s*(\d+)", 14)),
        "rsi_entry_below": float(g(r"RSI.{0,100}(?:BELOW|LESS THAN|<)\s*(\d+(?:\.\d+)?)", 30)),
        "rsi_exit_above": float(g(r"RSI.{0,100}(?:REACH(?:ES)?|ABOVE|GREATER THAN|>)\s*(\d+(?:\.\d+)?)", 55)),
        "bollinger_period": int(g(r"BOLLINGER(?:\s+BANDS?)?\s*\(?\s*(\d+)", 20)),
        "bollinger_std": float(g(r"BOLLINGER.{0,50}?(\d+(?:\.\d+)?)\s*(?:STD|STANDARD)", 2)),
        "risk_pct": float(g(r"RISK\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", 1)),
        "max_hold_hours": int(g(r"(\d+)\s*HOURS?", 0)) or None,
    }


def _activity(state: dict[str, Any], title: str, detail: str, status: str = "complete") -> None:
    items = list(state.get("activity", []))
    items.append({"time": datetime.now(timezone.utc).isoformat(), "title": title, "detail": detail, "status": status})
    state["activity"] = items[-20:]


def _criteria(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "instrument": s["symbol"],
        "timeframe": s["timeframe"],
        "lookback_days": s["lookback_days"],
        "entry": [
            f"RSI({s['rsi_period']}) < {s['rsi_entry_below']:g}",
            f"Low touches Bollinger lower band ({s['bollinger_period']}, {s['bollinger_std']:g}σ)",
        ],
        "exit": [f"RSI({s['rsi_period']}) >= {s['rsi_exit_above']:g}"] + ([f"Maximum hold {s['max_hold_hours']} hours"] if s.get("max_hold_hours") else []),
        "risk": f"{s['risk_pct']:g}% per trade",
        "indicators": [f"RSI {s['rsi_period']}", f"Bollinger Bands {s['bollinger_period']} / {s['bollinger_std']:g}σ"],
    }


def rsi(v: list[float], p: int) -> list[float | None]:
    out: list[float | None] = [None] * len(v)
    if len(v) <= p:
        return out
    gains = [max(v[i] - v[i - 1], 0.0) for i in range(1, len(v))]
    losses = [max(v[i - 1] - v[i], 0.0) for i in range(1, len(v))]
    avg_gain = sum(gains[:p]) / p
    avg_loss = sum(losses[:p]) / p
    for i in range(p, len(v)):
        if i > p:
            avg_gain = (avg_gain * (p - 1) + gains[i - 1]) / p
            avg_loss = (avg_loss * (p - 1) + losses[i - 1]) / p
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def bb(v: list[float], p: int, k: float) -> list[tuple[float, float, float] | None]:
    out: list[tuple[float, float, float] | None] = [None] * len(v)
    for i in range(p - 1, len(v)):
        w = v[i - p + 1:i + 1]
        mean = sum(w) / p
        sd = math.sqrt(sum((z - mean) ** 2 for z in w) / p)
        out[i] = (mean, mean - k * sd, mean + k * sd)
    return out


def bt(rows: list[dict[str, float | int]], s: dict[str, Any]) -> dict[str, Any]:
    closes = [float(x["close"]) for x in rows]
    lows = [float(x["low"]) for x in rows]
    times = [int(x["ts"]) for x in rows]
    rr = rsi(closes, s["rsi_period"])
    bands = bb(closes, s["bollinger_period"], s["bollinger_std"])
    entry: tuple[float, int] | None = None
    trades: list[dict[str, Any]] = []
    returns: list[float] = []
    hold = s["max_hold_hours"] * 3600000 if s.get("max_hold_hours") else None
    for i in range(1, len(rows)):
        if entry is None:
            if rr[i] is not None and bands[i] and rr[i] < s["rsi_entry_below"] and lows[i] <= bands[i][1]:
                entry = (closes[i], times[i])
            continue
        reason = "rsi_exit" if rr[i] is not None and rr[i] >= s["rsi_exit_above"] else "time_exit" if hold and times[i] - entry[1] >= hold else None
        if reason:
            pct = (closes[i] - entry[0]) / entry[0]
            returns.append(pct)
            trades.append({"entry_time": datetime.fromtimestamp(entry[1] / 1000, timezone.utc).isoformat(), "exit_time": datetime.fromtimestamp(times[i] / 1000, timezone.utc).isoformat(), "entry_price": round(entry[0], 8), "exit_price": round(closes[i], 8), "return_pct": round(pct * 100, 4), "risk_pct": s["risk_pct"], "exit_reason": reason})
            entry = None
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x <= 0]
    equity = peak = 1.0
    drawdown = 0.0
    for ret in returns:
        equity *= 1 + ret
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = sum((x - mean) ** 2 for x in returns) / len(returns) if returns else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    metrics = {
        "total_trades": len(returns), "trade_count": len(returns), "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) * 100 / len(returns), 2) if returns else 0.0,
        "total_return_pct": round((equity - 1) * 100, 2), "max_drawdown_pct": round(drawdown * 100, 2),
        "sharpe_ratio": round(mean / math.sqrt(variance) * math.sqrt(252), 3) if variance else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else 0.0,
        "risk_pct": s["risk_pct"], "final_equity_index": round(equity, 6),
    }
    return {"metrics": metrics, "trades": trades[-100:]}


def yf_symbol(s: str) -> str:
    return {"EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "JPY=X", "AUDUSD": "AUDUSD=X"}.get(s, s[:-3] + "-USD" if s.endswith("USD") else s)


def yi(tf: str) -> str:
    return {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "4h": "60m", "1d": "1d"}.get(tf, "15m")


def resample(rows: list[dict[str, float | int]], width: int = 14400000) -> list[dict[str, float | int]]:
    buckets: dict[int, list[dict[str, float | int]]] = {}
    for row in rows:
        buckets.setdefault(int(row["ts"]) // width * width, []).append(row)
    return [{"ts": k, "open": g[0]["open"], "high": max(z["high"] for z in g), "low": min(z["low"] for z in g), "close": g[-1]["close"]} for k, g in sorted(buckets.items())]


async def yahoo(symbol: str, tf: str, days: int) -> list[dict[str, float | int]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    interval = yi(tf)
    if interval in {"1m", "5m", "15m", "30m", "60m"}:
        start = max(start, end - timedelta(days=59))
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": "Mozilla/5.0"}) as c:
        r = await c.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol(symbol)}", params={"period1": int(start.timestamp()), "period2": int(end.timestamp()), "interval": interval, "events": "history"})
    r.raise_for_status()
    result = r.json().get("chart", {}).get("result", [None])[0]
    if not result:
        raise RuntimeError("Yahoo Finance returned no market data")
    q = result["indicators"]["quote"][0]
    rows: list[dict[str, float | int]] = []
    for i, ts in enumerate(result.get("timestamp", [])):
        try:
            rows.append({"ts": int(ts) * 1000, "open": float(q["open"][i]), "high": float(q["high"][i]), "low": float(q["low"][i]), "close": float(q["close"][i])})
        except (TypeError, ValueError, KeyError, IndexError):
            pass
    return resample(rows) if tf == "4h" else rows


async def mt5(uid: str, sid: str, s: dict[str, Any]) -> list[dict[str, float | int]]:
    now = datetime.now(timezone.utc)
    payload = {"user_id": uid, "strategy_id": sid, "symbol": s["symbol"], "timeframe": s["timeframe"], "date_from": (now - timedelta(days=s["lookback_days"])).isoformat(), "date_to": now.isoformat(), "status": "queued"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{SB}/rest/v1/mt5_bridge_jobs", headers=sh(), json=payload)
    if not r.is_success:
        raise RuntimeError("Could not queue MT5 market-data request")
    job_id = r.json()[0]["id"]
    deadline = asyncio.get_running_loop().time() + 90
    while asyncio.get_running_loop().time() < deadline:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{SB}/rest/v1/mt5_bridge_jobs", headers=sh(), params={"id": f"eq.{job_id}", "select": "status,rates,error", "limit": "1"})
        row = r.json()[0] if r.is_success and r.json() else None
        if row and row["status"] == "complete":
            return [{"ts": int(x["time"]) * 1000, "open": float(x["open"]), "high": float(x["high"]), "low": float(x["low"]), "close": float(x["close"])} for x in row["rates"]]
        if row and row["status"] == "failed":
            raise RuntimeError(row.get("error") or "MT5 bridge failed")
        await asyncio.sleep(2)
    raise RuntimeError("MT5 terminal did not respond in time")


async def _get_rows(uid: str, sid: str, s: dict[str, Any]) -> tuple[list[dict[str, float | int]], str]:
    try:
        return await mt5(uid, sid, s), "MT5"
    except Exception as mt5_error:
        try:
            rows = await yahoo(s["symbol"], s["timeframe"], s["lookback_days"])
            return rows, "Yahoo Finance"
        except Exception as yahoo_error:
            raise RuntimeError(f"Market data is temporarily unavailable. Please keep MetaTrader 5 open and connected, then retry. ({str(mt5_error)[:160]}; {str(yahoo_error)[:160]})")


async def run_research(strategy_id: str, user_id: str, token: str) -> None:
    """Research only. It stops at the explicit backtest confirmation gate."""
    try:
        if not await connected(user_id, token):
            state = (await load(strategy_id, user_id, token)).get("spec") or {}
            state["pipeline_stage"] = "awaiting_mt5_connection"
            state["pending_confirmation"] = "mt5_connection"
            state["agents"] = {**state.get("agents", {}), "research": "idle", "backtest": "idle", "indicator": "gated", "paper": "gated", "approval": "gated", "live": "gated"}
            _activity(state, "MT5 connection required", "Connect your MetaTrader 5 account before research can begin.", "blocked")
            await save(strategy_id, user_id, token, state, "awaiting_mt5")
            return

        strategy = await load(strategy_id, user_id, token)
        state = strategy.get("spec") or {}
        spec = parse(strategy.get("raw_strategy_text") or "")
        state["parsed_strategy"] = spec
        state["research_criteria"] = _criteria(spec)
        state["pipeline_stage"] = "research_running"
        state["pending_confirmation"] = None
        state["agents"] = {**state.get("agents", {}), "research": "running", "backtest": "queued", "indicator": "gated", "paper": "gated", "approval": "gated", "live": "gated"}
        _activity(state, "Research Agent started", f"Analysing {spec['symbol']} on {spec['timeframe']} using the defined RSI/Bollinger rules.", "running")
        await save(strategy_id, user_id, token, state, "research")

        rows, source = await _get_rows(user_id, strategy_id, spec)
        minimum = max(spec["rsi_period"], spec["bollinger_period"]) + 5
        if len(rows) < minimum:
            raise RuntimeError("Not enough market data for the requested indicators")
        closes = [float(x["close"]) for x in rows]
        rr = rsi(closes, spec["rsi_period"])
        bands = bb(closes, spec["bollinger_period"], spec["bollinger_std"])
        valid = sum(1 for i in range(len(rows)) if rr[i] is not None and bands[i] is not None)
        entry_candidates = sum(1 for i in range(len(rows)) if rr[i] is not None and bands[i] and rr[i] < spec["rsi_entry_below"] and float(rows[i]["low"]) <= bands[i][1])
        state["data_source"] = source
        state["data_source_message"] = "Market data is coming from your MetaTrader 5 account." if source == "MT5" else "The primary broker feed was unavailable, so the configured market-data fallback was used."
        state["bars_loaded"] = len(rows)
        state["research"] = {"status": "complete", "bars_checked": len(rows), "indicator_ready_bars": valid, "entry_candidates": entry_candidates, "criteria": state["research_criteria"], "data_source": source}
        state["pipeline_stage"] = "research_complete"
        state["pending_confirmation"] = "backtest"
        state["agents"] = {**state.get("agents", {}), "research": "complete", "backtest": "gated", "indicator": "gated", "paper": "gated", "approval": "gated", "live": "gated"}
        _activity(state, "Research Agent complete", f"Research verified {len(rows):,} bars and found {entry_candidates:,} historical entry candidates. Deterministic backtest is ready for confirmation.")
        await save(strategy_id, user_id, token, state, "research_complete")
    except Exception as exc:
        try:
            state = (await load(strategy_id, user_id, token)).get("spec") or {}
            state["pipeline_stage"] = "research_failed"
            state["error"] = "Research could not be completed. Please keep MetaTrader 5 open and connected, then retry."
            state["agents"] = {**state.get("agents", {}), "research": "failed", "backtest": "gated"}
            _activity(state, "Research Agent failed", str(exc)[:240], "failed")
            await save(strategy_id, user_id, token, state, "research_failed")
        except Exception:
            pass


async def run_backtest(strategy_id: str, user_id: str, token: str) -> None:
    """Deterministic backtest after the user confirms the research hand-off."""
    try:
        if not await connected(user_id, token):
            state = (await load(strategy_id, user_id, token)).get("spec") or {}
            state["pipeline_stage"] = "awaiting_mt5_connection"
            state["pending_confirmation"] = "mt5_connection"
            _activity(state, "Backtest paused", "Reconnect MetaTrader 5 before the deterministic backtest can continue.", "blocked")
            await save(strategy_id, user_id, token, state, "awaiting_mt5")
            return
        strategy = await load(strategy_id, user_id, token)
        state = strategy.get("spec") or {}
        spec = state.get("parsed_strategy") or parse(strategy.get("raw_strategy_text") or "")
        state["backtest_criteria"] = _criteria(spec)
        state["pipeline_stage"] = "backtest_running"
        state["pending_confirmation"] = None
        state["agents"] = {**state.get("agents", {}), "research": "complete", "backtest": "running", "indicator": "running", "paper": "gated", "approval": "gated", "live": "gated"}
        _activity(state, "Deterministic Backtest Agent started", f"Testing {spec['symbol']} with the exact research criteria; no LLM-generated performance numbers are used.", "running")
        await save(strategy_id, user_id, token, state, "backtesting")

        rows, source = await _get_rows(user_id, strategy_id, spec)
        result = bt(rows, spec)
        state["data_source"] = source
        state["bars_loaded"] = len(rows)
        state["backtest"] = {**result, "symbol": spec["symbol"], "timeframe": spec["timeframe"], "period_days": spec["lookback_days"], "data_source": source}
        state["pipeline_stage"] = "backtest_complete"
        state["pending_confirmation"] = "approval"
        state["agents"] = {**state.get("agents", {}), "research": "complete", "backtest": "complete", "indicator": "complete", "paper": "gated", "approval": "current", "live": "gated"}
        m = result["metrics"]
        _activity(state, "Deterministic Backtest complete", f"{m['trade_count']} trades · {m['win_rate']}% win rate · {m['total_return_pct']}% return · {m['max_drawdown_pct']}% max drawdown.")
        await save(strategy_id, user_id, token, state, "backtest_complete")
    except Exception as exc:
        try:
            state = (await load(strategy_id, user_id, token)).get("spec") or {}
            state["pipeline_stage"] = "backtest_failed"
            state["error"] = "The deterministic backtest could not be completed. Please keep MetaTrader 5 open and connected, then retry."
            state["agents"] = {**state.get("agents", {}), "backtest": "failed"}
            _activity(state, "Deterministic Backtest failed", str(exc)[:240], "failed")
            await save(strategy_id, user_id, token, state, "backtest_failed")
        except Exception:
            pass


async def run_pipeline(strategy_id: str, user_id: str, token: str) -> None:
    """Compatibility entry point: research only; backtest remains user-confirmed."""
    await run_research(strategy_id, user_id, token)


@api_router.get("/status/{strategy_id}")
async def status(strategy_id: str, user=Depends(get_current_user)):
    token = user.get("_access_token") or user.get("access_token")
    if not token:
        raise HTTPException(401, "Missing access token")
    strategy = await load(strategy_id, user["id"], token)
    state = strategy.get("spec") or {}
    return {"strategy_id": strategy_id, "status": strategy.get("status"), "pipeline_stage": state.get("pipeline_stage"), "agents": state.get("agents", {}), "activity": state.get("activity", []), "research": state.get("research"), "research_criteria": state.get("research_criteria"), "backtest": state.get("backtest"), "backtest_criteria": state.get("backtest_criteria"), "data_source": state.get("data_source"), "bars_loaded": state.get("bars_loaded"), "error": state.get("error")}
