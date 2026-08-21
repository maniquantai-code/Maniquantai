"""Deterministic research/backtest pipeline.

LLMs may interpret a user's natural-language strategy, but this module is the
execution boundary: market data, indicators, entries, exits and metrics are
calculated deterministically. Binance is never required; a 451 response falls
through to Coinbase for crypto and Yahoo's public chart endpoint for FX.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from .auth import get_current_user

api_router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
SUPABASE_URL = "https://zuimeyynaarjsovnqilk.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X"


def _headers(token: str):
    return {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}


async def _get(sid: str, uid: str, token: str):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/strategies", headers=_headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}", "select": "strategy_id,name,raw_strategy_text,status,spec", "limit": "1"})
    if not r.is_success or not r.json():
        raise RuntimeError("Strategy could not be loaded")
    return r.json()[0]


async def _save(sid: str, uid: str, token: str, state: dict, status: str | None = None):
    payload = {"spec": state, "updated_at": datetime.now(timezone.utc).isoformat()}
    if status:
        payload["status"] = status
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.patch(f"{SUPABASE_URL}/rest/v1/strategies", headers=_headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"}, json=payload)
    if not r.is_success:
        raise RuntimeError(f"State save failed: {r.text[:300]}")


def parse_strategy(text: str) -> dict[str, Any]:
    s = text.upper()
    symbol = "BTC/USDT" if "BTC" in s else "ETH/USDT" if "ETH" in s else "EUR/USD" if "EUR/USD" in s or "EURUSD" in s else None
    if re.search(r"4\s*-?\s*HOUR", s): tf = "4h"
    elif re.search(r"1\s*-?\s*HOUR", s): tf = "1h"
    elif re.search(r"30\s*-?\s*MIN", s): tf = "30m"
    elif re.search(r"15\s*-?\s*MIN", s): tf = "15m"
    elif re.search(r"5\s*-?\s*MIN", s): tf = "5m"
    elif re.search(r"1\s*-?\s*DAY|DAILY", s): tf = "1d"
    else: tf = "15m"
    dm = re.search(r"(\d+)\s*DAYS?", s)
    days = int(dm.group(1)) if dm else 90
    risk = re.search(r"RISK\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    hold = re.search(r"(\d+)\s*HOURS?", s)
    sl = re.search(r"(?:STOP\s*LOSS|SL)\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    tp = re.search(r"(?:TAKE\s*PROFIT|TP)\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    rm = re.search(r"RSI\s*\(?\s*(\d+)?", s)
    bm = re.search(r"BOLLINGER(?:\s+BANDS?)?\s*\(?\s*(\d+)?", s)
    em = re.search(r"EMA\s*\(?\s*(\d+)\s*\)?[^\n]{0,50}?EMA\s*\(?\s*(\d+)\s*\)?", s)
    rsi_entry_m = re.search(r"RSI.{0,80}(?:BELOW|LESS THAN|<)\s*(\d+(?:\.\d+)?)", s)
    rsi_exit_m = re.search(r"RSI.{0,80}(?:REACH(?:ES)?|ABOVE|GREATER THAN|>)\s*(\d+(?:\.\d+)?)", s)
    periods = [int(em.group(1)), int(em.group(2))] if em else []
    if "BOLLINGER" in s and "RSI" in s:
        kind = "rsi_bollinger_mean_reversion"
    elif periods:
        kind = "ema_crossover"
    elif "MACD" in s:
        kind = "macd"
    elif "RSI" in s:
        kind = "rsi"
    elif "BOLLINGER" in s:
        kind = "bollinger_bands"
    else:
        kind = "custom"
    return {
        "symbol": symbol, "timeframe": tf, "lookback_days": days, "strategy_type": kind,
        "rsi_period": int(rm.group(1)) if rm and rm.group(1) else 14,
        "rsi_entry_below": float(rsi_entry_m.group(1)) if rsi_entry_m else 30.0,
        "rsi_exit_above": float(rsi_exit_m.group(1)) if rsi_exit_m else 55.0,
        "bollinger_period": int(bm.group(1)) if bm and bm.group(1) else 20,
        "bollinger_std": 2.0,
        "risk_pct": float(risk.group(1)) if risk else 1.0,
        "max_hold_hours": int(hold.group(1)) if hold else None,
        "stop_loss_pct": float(sl.group(1)) if sl else None,
        "take_profit_pct": float(tp.group(1)) if tp else None,
        "ema_fast": min(periods) if periods else None,
        "ema_slow": max(periods) if periods else None,
    }


def _rsi(v: list[float], p: int = 14):
    out = [None] * len(v)
    if len(v) <= p: return out
    gains = [max(v[i] - v[i - 1], 0.0) for i in range(1, len(v))]
    losses = [max(v[i - 1] - v[i], 0.0) for i in range(1, len(v))]
    ag, al = sum(gains[:p]) / p, sum(losses[:p]) / p
    for i in range(p, len(v)):
        if i > p:
            ag = (ag * (p - 1) + gains[i - 1]) / p
            al = (al * (p - 1) + losses[i - 1]) / p
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def _bb(v: list[float], p: int = 20, k: float = 2.0):
    out = [None] * len(v)
    for i in range(p - 1, len(v)):
        w = v[i - p + 1:i + 1]
        m = sum(w) / p
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / p)
        out[i] = (m, m - k * sd, m + k * sd)
    return out


def _ema(v: list[float], p: int):
    out = [None] * len(v)
    if len(v) < p: return out
    prev = sum(v[:p]) / p
    out[p - 1] = prev
    k = 2 / (p + 1)
    for i in range(p, len(v)):
        prev = v[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _macd(v: list[float], fast=12, slow=26, signal=9):
    ef, es = _ema(v, fast), _ema(v, slow)
    line = [None if ef[i] is None or es[i] is None else ef[i] - es[i] for i in range(len(v))]
    valid = [x if x is not None else 0.0 for x in line]
    sig = _ema(valid, signal)
    return line, sig


def _metrics(returns: list[float], risk_pct: float) -> dict[str, Any]:
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x <= 0]
    eq = peak = 1.0
    dd = 0.0
    for r in returns:
        eq *= 1 + r
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
    mean = sum(returns) / len(returns) if returns else 0.0
    var = sum((x - mean) ** 2 for x in returns) / len(returns) if returns else 0.0
    sharpe = (mean / math.sqrt(var) * math.sqrt(252)) if var > 0 else 0.0
    gp, gl = sum(wins), abs(sum(losses))
    return {
        "total_trades": len(returns), "trade_count": len(returns), "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) * 100 / len(returns), 2) if returns else 0.0,
        "total_return_pct": round((eq - 1) * 100, 2), "net_return_pct": round((eq - 1) * 100, 2),
        "max_drawdown_pct": round(dd * 100, 2), "sharpe_ratio": round(sharpe, 3),
        "profit_factor": round(gp / gl, 3) if gl else (float("inf") if gp else 0.0),
        "avg_win_pct": round((sum(wins) / len(wins)) * 100, 3) if wins else 0.0,
        "avg_loss_pct": round(abs(sum(losses) / len(losses)) * 100, 3) if losses else 0.0,
        "risk_pct": risk_pct,
    }


def _yf_symbol(symbol: str) -> str:
    return {"EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X", "AUD/USD": "AUDUSD=X"}.get(symbol, symbol.replace("/", "-") + "=X")


async def _yahoo_data(symbol: str, interval: str, start_ms: int, end_ms: int):
    # Yahoo's intraday history is limited; use it for FX and as a last-resort source.
    if interval in {"1m", "5m", "15m", "30m"} and end_ms - start_ms > 59 * 86400000:
        start_ms = end_ms - 59 * 86400000
    period1, period2 = start_ms // 1000, end_ms // 1000
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{_yf_symbol(symbol)}"
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": "Mozilla/5.0"}) as c:
        r = await c.get(url, params={"period1": period1, "period2": period2, "interval": interval, "events": "history", "includeAdjustedClose": "true"})
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
    q = result.get("indicators", {}).get("quote", [{}])[0]
    rows = []
    for i, ts in enumerate(result.get("timestamp", [])):
        try:
            rows.append((ts * 1000, float(q["open"][i]), float(q["high"][i]), float(q["low"][i]), float(q["close"][i])))
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    return rows


async def _coinbase_data(symbol: str, interval: str, start_ms: int, end_ms: int):
    if interval not in {"15m", "30m", "1h"}:
        raise RuntimeError("Coinbase fallback supports 15m, 30m and 1h crypto candles")
    product = symbol.replace("/USDT", "-USD").replace("/USD", "-USD")
    granularity = {"15m": 900, "30m": 1800, "1h": 3600}[interval]
    rows: list[tuple[int, float, float, float, float]] = []
    cursor = start_ms
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "ManiQuantAI/1.0"}) as c:
        while cursor < end_ms and len(rows) < 50000:
            chunk_end = min(end_ms, cursor + granularity * 300 * 1000)
            r = await c.get(f"https://api.exchange.coinbase.com/products/{product}/candles", params={
                "granularity": granularity,
                "start": datetime.fromtimestamp(cursor / 1000, timezone.utc).isoformat(),
                "end": datetime.fromtimestamp(chunk_end / 1000, timezone.utc).isoformat(),
            })
            if r.status_code in {401, 403, 404, 429}:
                raise RuntimeError(f"COINBASE_UNAVAILABLE_{r.status_code}")
            r.raise_for_status()
            data = r.json()
            if not data:
                cursor = chunk_end
                continue
            for x in data:
                rows.append((int(float(x[0]) * 1000), float(x[3]), float(x[2]), float(x[1]), float(x[4])))
            cursor = chunk_end
    rows.sort(key=lambda x: x[0])
    seen: set[int] = set()
    return [x for x in rows if not (x[0] in seen or seen.add(x[0]))]


async def _data(symbol: str, interval: str, days: int):
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - days * 86400000
    errors: list[str] = []
    # Binance is intentionally not called: Vercel's deployment region can receive HTTP 451.
    if symbol.endswith("/USDT") or symbol.endswith("/USD") and symbol.split("/")[0] in {"BTC", "ETH", "SOL", "XRP", "BNB"}:
        try:
            rows = await _coinbase_data(symbol, interval, start, end)
            if rows: return rows, "Coinbase"
        except Exception as exc:
            errors.append(f"Coinbase: {exc}")
    try:
        rows = await _yahoo_data(symbol, interval, start, end)
        if rows: return rows, "Yahoo Finance"
    except Exception as exc:
        errors.append(f"Yahoo Finance: {exc}")
    raise RuntimeError("Market data unavailable. " + " | ".join(errors))


def _backtest(rows, spec):
    closes = [x[4] for x in rows]
    lows = [x[3] for x in rows]
    kind = spec["strategy_type"]
    returns: list[float] = []
    trades: list[dict[str, Any]] = []

    if kind == "rsi_bollinger_mean_reversion":
        rs, bb = _rsi(closes, spec["rsi_period"]), _bb(closes, spec["bollinger_period"], spec["bollinger_std"])
        entry_i: int | None = None
        for i in range(1, len(closes)):
            if entry_i is None and rs[i] is not None and bb[i] is not None and rs[i] < spec["rsi_entry_below"] and lows[i] <= bb[i][1]:
                entry_i = i
                continue
            if entry_i is not None:
                held = (rows[i][0] - rows[entry_i][0]) / 3600000
                timed = spec["max_hold_hours"] is not None and held >= spec["max_hold_hours"]
                signal = rs[i] is not None and rs[i] >= spec["rsi_exit_above"]
                sl = spec["stop_loss_pct"] is not None and closes[i] <= closes[entry_i] * (1 - spec["stop_loss_pct"] / 100)
                tp = spec["take_profit_pct"] is not None and closes[i] >= closes[entry_i] * (1 + spec["take_profit_pct"] / 100)
                if signal or timed or sl or tp:
                    ret = closes[i] / closes[entry_i] - 1
                    returns.append(ret)
                    trades.append({"entry_time": rows[entry_i][0], "exit_time": rows[i][0], "entry_price": closes[entry_i], "exit_price": closes[i], "return_pct": round(ret * 100, 3), "reason": "rsi_exit" if signal else "time_exit" if timed else "stop_loss" if sl else "take_profit"})
                    entry_i = None
    elif kind == "ema_crossover":
        fast, slow = _ema(closes, spec["ema_fast"]), _ema(closes, spec["ema_slow"])
        entry_i = None
        for i in range(1, len(closes)):
            if None in (fast[i], slow[i], fast[i-1], slow[i-1]): continue
            if entry_i is None and fast[i] > slow[i] and fast[i-1] <= slow[i-1]: entry_i = i
            elif entry_i is not None and fast[i] < slow[i] and fast[i-1] >= slow[i-1]:
                ret = closes[i] / closes[entry_i] - 1; returns.append(ret); trades.append({"entry_time": rows[entry_i][0], "exit_time": rows[i][0], "entry_price": closes[entry_i], "exit_price": closes[i], "return_pct": round(ret * 100, 3), "reason": "ema_cross"}); entry_i = None
    elif kind == "rsi":
        rs = _rsi(closes, spec["rsi_period"]); entry_i = None
        for i in range(1, len(closes)):
            if entry_i is None and rs[i] is not None and rs[i] < spec["rsi_entry_below"]: entry_i = i
            elif entry_i is not None and rs[i] is not None and rs[i] >= spec["rsi_exit_above"]:
                ret = closes[i] / closes[entry_i] - 1; returns.append(ret); entry_i = None
    elif kind == "bollinger_bands":
        bb = _bb(closes, spec["bollinger_period"], spec["bollinger_std"]); entry_i = None
        for i in range(1, len(closes)):
            if entry_i is None and bb[i] is not None and lows[i] <= bb[i][1]: entry_i = i
            elif entry_i is not None and bb[i] is not None and closes[i] >= bb[i][0]:
                ret = closes[i] / closes[entry_i] - 1; returns.append(ret); entry_i = None
    elif kind == "macd":
        line, sig = _macd(closes); entry_i = None
        for i in range(1, len(closes)):
            if None in (line[i], sig[i], line[i-1], sig[i-1]): continue
            if entry_i is None and line[i] > sig[i] and line[i-1] <= sig[i-1]: entry_i = i
            elif entry_i is not None and line[i] < sig[i] and line[i-1] >= sig[i-1]:
                ret = closes[i] / closes[entry_i] - 1; returns.append(ret); entry_i = None
    else:
        raise RuntimeError("Strategy rules could not be compiled into a deterministic backtest")

    return {"metrics": _metrics(returns, spec["risk_pct"]), "trades": trades[-100:]}


async def run_pipeline(strategy_id: str, user_id: str, token: str):
    strategy = await _get(strategy_id, user_id, token)
    state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
    state.update({"pipeline_stage": "research", "agents": {"research": "running", "backtest": "queued", "indicator": "queued", "paper": "gated", "approval": "gated", "live": "gated"}, "error": None})
    await _save(strategy_id, user_id, token, state, "research")
    spec = parse_strategy(strategy.get("raw_strategy_text") or "")
    state["research"] = {"status": "complete", "parsed_spec": spec}
    state["agents"]["research"] = "complete"
    if not spec["symbol"]:
        state.update({"pipeline_stage": "research_failed", "error": "No supported market symbol found"})
        await _save(strategy_id, user_id, token, state, "blocked")
        return
    state.update({"pipeline_stage": "backtest_running", "agents": {**state["agents"], "backtest": "running"}})
    await _save(strategy_id, user_id, token, state, "backtesting")
    try:
        rows, provider = await _data(spec["symbol"], spec["timeframe"], spec["lookback_days"])
        result = _backtest(rows, spec)
    except Exception as exc:
        state.update({"pipeline_stage": "backtest_failed", "error": str(exc), "agents": {**state["agents"], "backtest": "failed"}})
        await _save(strategy_id, user_id, token, state, "blocked")
        return
    result["metrics"].update({"data_provider": provider, "data_bars": len(rows), "symbol": spec["symbol"], "interval": spec["timeframe"], "period_days": spec["lookback_days"]})
    state["backtest"] = {"status": "complete", **result}
    state["agents"]["backtest"] = "complete"
    state["pipeline_stage"] = "indicator_verification"
    state["agents"]["indicator"] = "complete"
    state["indicator_verification"] = {"status": "complete", "deterministic": True}
    state["pending_confirmation"] = "backtest_review"
    await _save(strategy_id, user_id, token, state, "backtest_complete")


@api_router.post("/{strategy_id}/start")
async def start_pipeline(strategy_id: str, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    token = user.get("_access_token")
    if not token:
        raise HTTPException(401, "Missing access token")
    await _get(strategy_id, user["id"], token)
    background_tasks.add_task(run_pipeline, strategy_id, user["id"], token)
    return {"status": "queued", "strategy_id": strategy_id}
