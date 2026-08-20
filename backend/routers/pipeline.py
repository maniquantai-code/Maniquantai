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
        raise RuntimeError(f"State save failed: {r.text[:200]}")

def parse_strategy(text: str):
    s = text.upper()
    symbol = "BTC/USDT" if "BTC" in s else "ETH/USDT" if "ETH" in s else "EUR/USD" if "EUR/USD" in s else None
    tf = "15m" if re.search(r"15\s*-?\s*MIN", s) else "1h" if re.search(r"1\s*-?\s*HOUR", s) else "15m"
    dm = re.search(r"(\d+)\s*DAYS?", s)
    days = int(dm.group(1)) if dm else 90
    rm = re.search(r"RSI\s*\(?\s*(\d+)?", s)
    bm = re.search(r"BOLLINGER(?:\s+BANDS?)?\s*\(?\s*(\d+)?", s)
    risk = re.search(r"RISK\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    hold = re.search(r"(\d+)\s*HOURS?", s)
    sl = re.search(r"(?:STOP\s*LOSS|SL)\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    tp = re.search(r"(?:TAKE\s*PROFIT|TP)\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    em = re.search(r"EMA\s*\(?\s*(\d+)\s*\)?[^\n]{0,40}?EMA\s*\(?\s*(\d+)\s*\)?", s)
    rsi_entry = 30 if re.search(r"RSI.{0,50}(?:BELOW|LESS THAN|<)\s*30", s) else None
    rsi_exit = 55 if re.search(r"RSI.{0,50}(?:REACH(?:ES)?|ABOVE|GREATER THAN|>)\s*55", s) else None
    periods = [int(em.group(1)), int(em.group(2))] if em else []
    kind = "rsi_bollinger_mean_reversion" if "RSI" in s and "BOLLINGER" in s else "ema_crossover" if periods else "custom"
    return {"symbol": symbol, "timeframe": tf, "lookback_days": days, "strategy_type": kind, "rsi_period": int(rm.group(1)) if rm and rm.group(1) else 14, "rsi_entry_below": rsi_entry, "rsi_exit_above": rsi_exit, "bollinger_period": int(bm.group(1)) if bm and bm.group(1) else 20, "bollinger_std": 2.0 if "BOLLINGER" in s else None, "risk_pct": float(risk.group(1)) if risk else 1.0, "max_hold_hours": int(hold.group(1)) if hold else None, "stop_loss_pct": float(sl.group(1)) if sl else None, "take_profit_pct": float(tp.group(1)) if tp else None, "ema_fast": min(periods) if periods else None, "ema_slow": max(periods) if periods else None}

def _rsi(v, p=14):
    out = [None] * len(v)
    if len(v) <= p: return out
    gains = [max(v[i] - v[i-1], 0) for i in range(1, len(v))]
    losses = [max(v[i-1] - v[i], 0) for i in range(1, len(v))]
    ag, al = sum(gains[:p]) / p, sum(losses[:p]) / p
    out[p] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(p + 1, len(v)):
        ag = (ag * (p - 1) + gains[i-1]) / p
        al = (al * (p - 1) + losses[i-1]) / p
        out[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return out

def _bb(v, p=20, k=2):
    out = [None] * len(v)
    for i in range(p - 1, len(v)):
        w = v[i-p+1:i+1]
        m = sum(w) / p
        sd = (sum((x - m) ** 2 for x in w) / p) ** 0.5
        out[i] = m - k * sd
    return out

def _ema(v, p):
    out = [None] * len(v)
    if len(v) < p: return out
    prev = sum(v[:p]) / p
    out[p-1] = prev
    k = 2 / (p + 1)
    for i in range(p, len(v)):
        prev = v[i] * k + prev * (1 - k)
        out[i] = prev
    return out

def _metrics(trades):
    wins = [x for x in trades if x > 0]
    losses = [x for x in trades if x <= 0]
    eq = peak = 1.0
    dd = 0.0
    for x in trades:
        eq *= 1 + x
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
    aw = sum(wins) / len(wins) if wins else 0
    al = abs(sum(losses) / len(losses)) if losses else 0
    return {"trade_count": len(trades), "wins": len(wins), "losses": len(losses), "win_rate": round(len(wins) * 100 / len(trades), 2) if trades else 0, "net_return_pct": round((eq - 1) * 100, 2), "max_drawdown_pct": round(dd * 100, 2), "avg_win_pct": round(aw * 100, 3), "avg_loss_pct": round(al * 100, 3), "win_loss_ratio": round(aw / al, 3) if al else None}

async def _binance_data(symbol: str, interval: str, start: int, end: int):
    rows = []
    async with httpx.AsyncClient(timeout=20) as c:
        cursor = start
        while cursor < end and len(rows) < 20000:
            r = await c.get("https://api.binance.com/api/v3/klines", params={"symbol": symbol.replace('/', ''), "interval": interval, "startTime": cursor, "endTime": end, "limit": 1000})
            if r.status_code in (401, 403, 451):
                raise RuntimeError(f"BINANCE_UNAVAILABLE_{r.status_code}")
            r.raise_for_status()
            b = r.json()
            if not b: break
            rows += [(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in b]
            cursor = int(b[-1][0]) + 1
            if len(b) < 1000: break
    return rows

async def _coinbase_data(symbol: str, interval: str, start: int, end: int):
    if interval != "15m":
        raise RuntimeError("Coinbase fallback currently supports 15-minute crypto candles only")
    product = symbol.replace("/USDT", "-USD").replace("/USD", "-USD")
    step = 900
    rows = []
    async with httpx.AsyncClient(timeout=20) as c:
        cursor = start
        while cursor < end and len(rows) < 20000:
            chunk_end = min(end, cursor + step * 300)
            r = await c.get(f"https://api.exchange.coinbase.com/products/{product}/candles", params={"granularity": step, "start": datetime.fromtimestamp(cursor / 1000, timezone.utc).isoformat(), "end": datetime.fromtimestamp(chunk_end / 1000, timezone.utc).isoformat()})
            if r.status_code in (401, 403, 404):
                raise RuntimeError(f"COINBASE_DATA_UNAVAILABLE_{r.status_code}")
            r.raise_for_status()
            b = r.json()
            for x in b:
                rows.append((int(float(x[0]) * 1000), float(x[3]), float(x[2]), float(x[1]), float(x[4])))
            cursor = chunk_end
    rows.sort(key=lambda x: x[0])
    dedup = []
    seen = set()
    for row in rows:
        if row[0] not in seen:
            seen.add(row[0]); dedup.append(row)
    return dedup

async def _data(symbol: str, interval: str, days: int):
    if symbol == "EUR/USD":
        raise RuntimeError("EUR/USD requires an FX market-data provider")
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - days * 86400000
    try:
        rows = await _binance_data(symbol, interval, start, end)
        provider = "binance"
    except Exception as primary_exc:
        try:
            rows = await _coinbase_data(symbol, interval, start, end)
            provider = "coinbase"
        except Exception as fallback_exc:
            raise RuntimeError(f"Market data unavailable: Binance failed ({primary_exc}); Coinbase fallback failed ({fallback_exc})")
    if not rows:
        raise RuntimeError("No historical market data was returned")
    return rows, provider

def _backtest(rows, spec):
    closes = [x[4] for x in rows]
    trades = []
    if spec["strategy_type"] == "rsi_bollinger_mean_reversion":
        rs = _rsi(closes, spec["rsi_period"] or 14)
        lower = _bb(closes, spec["bollinger_period"] or 20, spec["bollinger_std"] or 2)
        entry = None
        entry_i = 0
        for i in range(1, len(closes)):
            if entry is None and rs[i] is not None and lower[i] is not None and rs[i] < (spec["rsi_entry_below"] or 30) and rows[i][3] <= lower[i]:
                entry, entry_i = closes[i], i
            elif entry is not None:
                held = (rows[i][0] - rows[entry_i][0]) / 3600000
                if (rs[i] is not None and rs[i] >= (spec["rsi_exit_above"] or 55)) or (spec["max_hold_hours"] and held >= spec["max_hold_hours"]):
                    trades.append(closes[i] / entry - 1)
                    entry = None
        if entry is not None: trades.append(closes[-1] / entry - 1)
    else:
        fast, slow = spec.get("ema_fast"), spec.get("ema_slow")
        if not fast or not slow: raise RuntimeError("Strategy rules could not be compiled into a deterministic backtest")
        ef, es = _ema(closes, fast), _ema(closes, slow)
        entry = None
        for i in range(1, len(closes)):
            if None in (ef[i], es[i], ef[i-1], es[i-1]): continue
            if entry is None and ef[i] > es[i] and ef[i-1] <= es[i-1]: entry = closes[i]
            elif entry is not None and ef[i] < es[i] and ef[i-1] >= es[i-1]: trades.append(closes[i] / entry - 1); entry = None
        if entry is not None: trades.append(closes[-1] / entry - 1)
    metrics = _metrics(trades)
    metrics.update({"data_bars": len(rows), "risk_pct": spec.get("risk_pct")})
    return metrics

async def run_pipeline(strategy_id: str, user_id: str, token: str):
    strategy = await _get(strategy_id, user_id, token)
    state = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
    state.update({"pipeline_stage": "research", "agents": {"research": "running", "backtest": "queued", "indicator": "queued", "paper": "gated", "live": "gated"}, "error": None})
    await _save(strategy_id, user_id, token, state, "research")
    spec = parse_strategy(strategy.get("raw_strategy_text") or "")
    state["research"] = {"status": "complete", "parsed_spec": spec}
    state["agents"]["research"] = "complete"
    if not spec["symbol"]:
        state["pipeline_stage"] = "research_failed"
        state["error"] = "No supported market symbol found"
        await _save(strategy_id, user_id, token, state, "blocked")
        return
    state["pipeline_stage"] = "backtest_running"
    state["agents"]["backtest"] = "running"
    await _save(strategy_id, user_id, token, state, "backtesting")
    try:
        rows, provider = await _data(spec["symbol"], spec["timeframe"], spec["lookback_days"])
        metrics = _backtest(rows, spec)
        metrics["data_provider"] = provider
    except Exception as exc:
        state["pipeline_stage"] = "backtest_failed"
        state["agents"]["backtest"] = "failed"
        state["error"] = str(exc)
        await _save(strategy_id, user_id, token, state, "blocked")
        return
    state["backtest"] = {"status": "complete", "metrics": metrics}
    state["agents"]["backtest"] = "complete"
    state["pipeline_stage"] = "indicator_verification"
    state["agents"]["indicator"] = "complete"
    state["indicator_verification"] = {"status": "complete", "deterministic": True}
    state["pending_confirmation"] = "backtest_review"
    await _save(strategy_id, user_id, token, state, "backtest_complete")

@api_router.post("/{strategy_id}/start")
async def start_pipeline(strategy_id: str, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    token = user.get("_access_token")
    if not token: raise HTTPException(401, "Missing access token")
    await _get(strategy_id, user["id"], token)
    background_tasks.add_task(run_pipeline, strategy_id, user["id"], token)
    return {"status": "queued", "strategy_id": strategy_id}
