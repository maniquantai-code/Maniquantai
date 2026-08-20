"""Deterministic strategy research and backtest pipeline."""
from __future__ import annotations
import re
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from .auth import get_current_user

api_router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
SUPABASE_URL = "https://zuimeyynaarjsovnqilk.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X"

def _headers(token: str):
    return {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}

async def _get(strategy_id: str, user_id: str, token: str):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/strategies", headers=_headers(token), params={
            "strategy_id": f"eq.{strategy_id}", "user_id": f"eq.{user_id}",
            "select": "strategy_id,name,raw_strategy_text,status,spec", "limit": "1"
        })
    if not r.is_success or not r.json():
        raise RuntimeError("Strategy could not be loaded")
    return r.json()[0]

async def _save(strategy_id: str, user_id: str, token: str, spec: dict, status: str | None = None):
    payload = {"spec": spec, "updated_at": datetime.now(timezone.utc).isoformat()}
    if status:
        payload["status"] = status
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.patch(f"{SUPABASE_URL}/rest/v1/strategies", headers=_headers(token), params={
            "strategy_id": f"eq.{strategy_id}", "user_id": f"eq.{user_id}"
        }, json=payload)
    if not r.is_success:
        raise RuntimeError(f"State save failed: {r.text[:200]}")

def _parse(text: str):
    s = text.upper()
    symbol = "BTC/USDT" if "BTC" in s else ("ETH/USDT" if "ETH" in s else None)
    if "EUR/USD" in s:
        symbol = "EUR/USD"
    tf = "15m" if "15-MIN" in s or "15M" in s else ("1h" if "1-HOUR" in s or "1H" in s else "15m")
    day_match = re.search(r"(\d+)\s*DAYS?", s)
    days = int(day_match.group(1)) if day_match else 90
    rsi_match = re.search(r"RSI\s*(?:\(?\s*)?(\d+)?", s)
    bb_match = re.search(r"BOLLINGER(?:\s+BANDS?)?.{0,40}?(\d+)?", s)
    rsi_period = int(rsi_match.group(1)) if rsi_match and rsi_match.group(1) else 14
    bb_period = int(bb_match.group(1)) if bb_match and bb_match.group(1) else 20
    ema_match = re.search(r"EMA\s*\(?\s*(\d+)\s*\)?[^\n]{0,30}?EMA\s*\(?\s*(\d+)\s*\)?", s)
    periods = [int(ema_match.group(1)), int(ema_match.group(2))] if ema_match else []
    risk_match = re.search(r"RISK\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    hold_match = re.search(r"(\d+)\s*HOURS?", s)
    sl_match = re.search(r"(?:STOP\s*LOSS|SL)\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    tp_match = re.search(r"(?:TAKE\s*PROFIT|TP)\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    return {
        "symbol": symbol, "timeframe": tf, "lookback_days": days,
        "ema_fast": min(periods) if periods else None, "ema_slow": max(periods) if periods else None,
        "rsi_period": rsi_period if "RSI" in s else None,
        "rsi_entry_below": 30 if "RSI" in s and re.search(r"RSI.{0,30}(?:BELOW|<)\s*30", s) else None,
        "rsi_exit_above": 55 if "RSI" in s and re.search(r"RSI.{0,30}(?:REACH|REACHES|ABOVE|>)\s*55", s) else None,
        "bollinger_period": bb_period if "BOLLINGER" in s else None,
        "bollinger_std": 2.0 if "BOLLINGER" in s else None,
        "risk_pct": float(risk_match.group(1)) if risk_match else None,
        "max_hold_hours": int(hold_match.group(1)) if hold_match else None,
        "stop_loss_pct": float(sl_match.group(1)) if sl_match else None,
        "take_profit_pct": float(tp_match.group(1)) if tp_match else None,
        "strategy_type": "rsi_bollinger_mean_reversion" if "RSI" in s and "BOLLINGER" in s else ("ema_crossover" if periods else "custom")
    }

async def _binance_klines(symbol: str, interval: str, days: int):
    if symbol == "EUR/USD":
        raise RuntimeError("EUR/USD requires the configured FX market-data provider; Binance cannot supply forex candles.")
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - days * 86400000
    rows = []
    async with httpx.AsyncClient(timeout=20) as c:
        while start < end and len(rows) < 20000:
            r = await c.get("https://api.binance.com/api/v3/klines", params={"symbol": symbol.replace("/", ""), "interval": interval, "startTime": start, "endTime": end, "limit": 1000})
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            rows.extend((int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in batch)
            start = int(batch[-1][0]) + 1
            if len(batch) < 1000:
                break
    return rows

def _ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    k = 2 / (period + 1)
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out

def _rsi(values, period=14):
    out = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [max(values[i] - values[i - 1], 0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0) for i in range(1, len(values))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return out

def _bollinger(values, period=20, stds=2.0):
    lower = [None] * len(values)
    if len(values) < period:
        return lower
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        lower[i] = mean - stds * (variance ** 0.5)
    return lower

def _metrics(trades):
    wins = [p for p in trades if p > 0]
    losses = [p for p in trades if p <= 0]
    equity = peak = 1.0
    max_dd = 0.0
    for p in trades:
        equity *= 1 + p
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    aw = sum(wins) / len(wins) if wins else 0
    al = abs(sum(losses) / len(losses)) if losses else 0
    return {"trade_count": len(trades), "wins": len(wins), "losses": len(losses), "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0, "net_return_pct": round((equity - 1) * 100, 2), "max_drawdown_pct": round(max_dd * 100, 2), "avg_win_pct": round(aw * 100, 3), "avg_loss_pct": round(al * 100, 3), "win_loss_ratio": round(aw / al, 3) if al else None}

def _backtest(rows, spec):
    closes = [x[4] for x in rows]
    trades = []
    if spec["strategy_type"] == "rsi_bollinger_mean_reversion":
        rsis = _rsi(closes, spec["rsi_period"] or 14)
        lower = _bollinger(closes, spec["bollinger_period"] or 20, spec["bollinger_std"] or 2)
        in_pos = False
        entry = 0.0
        entry_index = 0
        for i in range(1, len(closes)):
            if not in_pos and rsis[i] is not None and lower[i] is not None and rsis[i] < (spec["rsi_entry_below"] or 30) and rows[i][3] <= lower[i]:
                in_pos, entry, entry_index = True, closes[i], i
            elif in_pos:
                held_hours = (rows[i][0] - rows[entry_index][0]) / 3600000
                if (rsis[i] is not None and rsis[i] >= (spec["rsi_exit_above"] or 55)) or (spec["max_hold_hours"] and held_hours >= spec["max_hold_hours"]):
                    trades.append(closes[i] / entry - 1)
                    in_pos = False
        if in_pos:
            trades.append(closes[-1] / entry - 1)
    else:
        fast, slow = spec.get("ema_fast"), spec.get("ema_slow")
        if not fast or not slow:
            raise RuntimeError("Strategy rules could not be compiled into a deterministic backtest.")
        ef, es = _ema(closes, fast), _ema(closes, slow)
        in_pos, entry = False, 0.0
        for i in range(1, len(closes)):
            if None in (ef[i], es[i], ef[i - 1], es[i - 1]):
                continue
            up = ef[i] > es[i] and ef[i - 1] <= es[i - 1]
            down = ef[i] < es[i] and ef[i - 1] >= es[i - 1]
            if not in_pos and up:
                in_pos, entry = True, closes[i]
            elif in_pos and down:
                trades.append(closes[i] / entry - 1)
                in_pos = False
        if in_pos and entry:
            trades.append(closes[-1] / entry - 1)
    result = _metrics(trades)
    result["data_bars"] = len(rows)
    result["risk_pct"] = spec.get("risk_pct")
    return result

async def run_pipeline(strategy_id: str, user_id: str, token: str):
    strategy = await _get(strategy_id, user_id, token)
    state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
    state["pipeline_stage"] = "research"
    state["agents"] = {"research": "running", "backtest": "queued", "indicator": "queued", "paper": "gated", "live": "gated"}
    state["research"] = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
    await _save(strategy_id, user_id, token, state, "research")
    spec = _parse(strategy.get("raw_strategy_text") or "")
    state["research"] = {"status": "complete", "parsed_spec": spec, "completed_at": datetime.now(timezone.utc).isoformat()}
    state["agents"]["research"] = "complete"
    if not spec["symbol"]:
        state["pipeline_stage"] = "research_failed"
        state["error"] = "No supported market symbol was found in the strategy."
        await _save(strategy_id, user_id, token, state, "blocked")
        return
    state["pipeline_stage"] = "backtest_running"
    state["agents"]["backtest"] = "running"
    await _save(strategy_id, user_id, token, state, "backtesting")
    try:
        rows = await _binance_klines(spec["symbol"], spec["timeframe"], spec["lookback_days"])
        metrics = _backtest(rows, spec)
    except Exception as exc:
        state["pipeline_stage"] = "backtest_failed"
        state["agents"]["backtest"] = "failed"
        state["error"] = str(exc)
        await _save(strategy_id, user_id, token, state, "blocked")
        return
    state["backtest"] = {"status": "complete", "metrics": metrics, "completed_at": datetime.now(timezone.utc).isoformat()}
    state["agents"]["backtest"] = "complete"
    state["pipeline_stage"] = "indicator_verification"
    state["agents"]["indicator"] = "complete"
    state["indicator_verification"] = {"status": "complete", "checks": ["rules parsed", "indicators calculated deterministically", "trade simulation completed"]}
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
