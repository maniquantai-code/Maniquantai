"""ManiQuantAI v2 — production pipeline. Deterministic, no raw errors to users."""
from __future__ import annotations
import asyncio, logging, math, os, re
from datetime import datetime, timezone, timedelta
from typing import Any
import httpx
from fastapi import APIRouter, Depends, HTTPException
from .auth import get_current_user

log = logging.getLogger("maniquantai.pipeline")
api_router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
SB      = os.getenv("SUPABASE_URL", "https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
ANON    = os.getenv("SUPABASE_ANON_KEY", "sb_publishable_Uf0ECWKkKrH6pzedVbTOA_aNlp1J1X").strip()
SERVICE = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

def h(token: str) -> dict:
    return {"apikey": ANON, "Authorization": f"Bearer {token}",
            "Content-Type": "application/json", "Prefer": "return=representation"}
def sh() -> dict:
    if not SERVICE:
        raise RuntimeError("Service role key not configured")
    return {"apikey": SERVICE, "Authorization": f"Bearer {SERVICE}",
            "Content-Type": "application/json", "Prefer": "return=representation"}

async def load(sid: str, uid: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{SB}/rest/v1/strategies", headers=h(token),
                        params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}",
                                "select": "strategy_id,name,raw_strategy_text,status,spec", "limit": "1"})
    if not r.is_success or not r.json():
        raise RuntimeError("Strategy not found")
    return r.json()[0]

async def save(sid: str, uid: str, token: str, state: dict, status: str | None = None) -> None:
    payload = {"spec": state, "updated_at": datetime.now(timezone.utc).isoformat()}
    if status:
        payload["status"] = status
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.patch(f"{SB}/rest/v1/strategies", headers=h(token),
                          params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"}, json=payload)
    except Exception as e:
        log.error("Save failed: %s", e)

async def connected(uid: str, token: str) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{SB}/rest/v1/broker_accounts", headers=h(token),
                            params={"user_id": f"eq.{uid}", "connector_type": "eq.mt5",
                                    "bridge_enabled": "eq.true", "last_verified_at": f"gte.{cutoff}",
                                    "select": "id", "limit": "1"})
        return bool(r.is_success and r.json())
    except Exception:
        return False

def _act(state: dict, title: str, detail: str, status: str = "complete") -> None:
    items = list(state.get("activity", []))
    items.append({"time": datetime.now(timezone.utc).isoformat(),
                  "title": title, "detail": detail, "status": status})
    state["activity"] = items[-30:]

def _parse(raw: str) -> dict:
    """Use v2 compiler if available, fall back to regex."""
    try:
        from ..core.strategy_compiler_v2 import compile_strategy_v2
        result = compile_strategy_v2(raw)
        rt = result.get("runtime", {})
        if rt.get("symbol"):
            return rt
    except Exception:
        pass
    s = raw.upper()
    def g(pat, default):
        m = re.search(pat, s)
        return m.group(1) if m else default
    # Symbol
    sym_map = {"BTC": "BTCUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "BNB": "BNBUSD",
               "XRP": "XRPUSD", "ADA": "ADAUSD", "DOGE": "DOGEUSD", "LTC": "LTCUSD",
               "AVAX": "AVAXUSD", "LINK": "LINKUSD", "MATIC": "MATICUSD",
               "GOLD": "XAUUSD", "XAU": "XAUUSD", "EUR": "EURUSD", "GBP": "GBPUSD"}
    symbol = next((v for k, v in sym_map.items() if k in s), "BTCUSD")
    tf_map = [("4H", "4h"), ("1H", "1h"), ("30M", "30m"), ("15M", "15m"), ("5M", "5m"), ("1D", "1d")]
    tf = next((v for k, v in tf_map if k in s.replace(" ", "").replace("-", "")), "15m")
    return {
        "symbol": symbol, "timeframe": tf,
        "lookback_days": int(g(r"(\d+)\s*DAYS?", 90)),
        "rsi_period": int(g(r"RSI\s*\(?\s*(\d+)", 14)),
        "rsi_entry_below": float(g(r"RSI.{0,80}(?:BELOW|UNDER|<)\s*(\d+(?:\.\d+)?)", 30)),
        "rsi_exit_above": float(g(r"RSI.{0,80}(?:ABOVE|OVER|>|EXIT)\s*(\d+(?:\.\d+)?)", 55)),
        "bollinger_period": int(g(r"BOLLINGER\s*\(?\s*(\d+)", 20)),
        "bollinger_std": float(g(r"BOLLINGER.{0,40}(\d+(?:\.\d+)?)\s*(?:STD|SIGMA|σ)", 2.0)),
        "risk_pct": min(float(g(r"RISK\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", 1.0)), 2.0),
        "max_hold_hours": int(g(r"(\d+)\s*HOURS?", 0)) or None,
        "stop_loss": {"type": "ATR", "period": 14, "multiplier": 1.5},
        "take_profit": {"type": "R_MULTIPLE", "multiple": 2.0},
        "max_open_positions": 1,
    }

def _criteria(s: dict) -> dict:
    return {
        "instrument": s.get("symbol", "?"), "timeframe": s.get("timeframe", "?"),
        "lookback_days": s.get("lookback_days", 90),
        "entry": [f"RSI({s.get('rsi_period',14)}) < {s.get('rsi_entry_below',30)}",
                  f"Price at lower Bollinger Band({s.get('bollinger_period',20)}, {s.get('bollinger_std',2.0)}σ)"],
        "exit": [f"RSI({s.get('rsi_period',14)}) ≥ {s.get('rsi_exit_above',55)}",
                 f"ATR(14) × {(s.get('stop_loss') or {}).get('multiplier', 1.5)} stop loss"],
        "risk": f"{s.get('risk_pct',1)}% per trade",
    }

# ── Indicators ────────────────────────────────────────────────────────────────
def rsi_calc(v: list[float], p: int) -> list[float | None]:
    out: list[float | None] = [None] * len(v)
    if len(v) <= p: return out
    gains = [max(v[i]-v[i-1], 0.0) for i in range(1, len(v))]
    losses = [max(v[i-1]-v[i], 0.0) for i in range(1, len(v))]
    ag = sum(gains[:p]) / p; al = sum(losses[:p]) / p
    for i in range(p, len(v)):
        if i > p:
            ag = (ag*(p-1)+gains[i-1])/p; al = (al*(p-1)+losses[i-1])/p
        out[i] = 100.0 if al == 0 else 100.0 - 100.0/(1.0+ag/al)
    return out

def bb_calc(v: list[float], p: int, k: float) -> list[tuple | None]:
    out: list[tuple | None] = [None] * len(v)
    for i in range(p-1, len(v)):
        w = v[i-p+1:i+1]; mean = sum(w)/p
        sd = math.sqrt(sum((z-mean)**2 for z in w)/p)
        out[i] = (mean, mean-k*sd, mean+k*sd)
    return out

def run_bt(rows: list[dict], s: dict) -> dict:
    closes = [float(x["close"]) for x in rows]
    lows   = [float(x.get("low", x["close"])) for x in rows]
    times  = [int(x.get("ts", x.get("time", 0))) for x in rows]
    rr     = rsi_calc(closes, s.get("rsi_period", 14))
    bands  = bb_calc(closes, s.get("bollinger_period", 20), s.get("bollinger_std", 2.0))
    entry  = None; trades = []; returns = []
    hold   = (s.get("max_hold_hours") or 0) * 3_600_000 or None
    for i in range(1, len(rows)):
        if entry is None:
            if rr[i] is not None and bands[i] and rr[i] < s.get("rsi_entry_below", 30) and lows[i] <= bands[i][1]:
                entry = (closes[i], times[i])
        else:
            rsi_exit  = rr[i] is not None and rr[i] >= s.get("rsi_exit_above", 55)
            time_exit = hold and times[i] - entry[1] >= hold
            if rsi_exit or time_exit:
                pct = (closes[i] - entry[0]) / entry[0]
                returns.append(pct)
                trades.append({"entry_price": round(entry[0], 6), "exit_price": round(closes[i], 6),
                               "return_pct": round(pct*100, 4), "exit_reason": "rsi" if rsi_exit else "time"})
                entry = None
    wins   = [x for x in returns if x > 0]
    losses = [x for x in returns if x <= 0]
    equity = peak = 1.0; dd = 0.0
    for r in returns:
        equity *= 1+r; peak = max(peak, equity); dd = max(dd, (peak-equity)/peak)
    mean = sum(returns)/len(returns) if returns else 0.0
    var  = sum((x-mean)**2 for x in returns)/len(returns) if returns else 0.0
    gp   = sum(wins); gl = abs(sum(losses))
    return {"metrics": {
        "trade_count": len(returns), "total_trades": len(returns),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins)*100/len(returns), 2) if returns else 0.0,
        "total_return_pct": round((equity-1)*100, 2),
        "max_drawdown_pct": round(dd*100, 2),
        "sharpe_ratio": round(mean/math.sqrt(var)*math.sqrt(252), 3) if var else 0.0,
        "profit_factor": round(gp/gl, 3) if gl else 0.0,
        "risk_pct": s.get("risk_pct", 1),
    }, "trades": trades[-100:]}

# ── Market data ───────────────────────────────────────────────────────────────
def yf_symbol(s: str) -> str:
    forex = {"EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"JPY=X","AUDUSD":"AUDUSD=X",
             "NZDUSD":"NZDUSD=X","USDCAD":"CAD=X","USDCHF":"CHF=X","XAUUSD":"GC=F",
             "XAGUSD":"SI=F","US30":"^DJI","NAS100":"^NDX","SP500":"^GSPC"}
    if s in forex: return forex[s]
    if s.endswith("USD") and len(s) > 3: return s[:-3]+"-USD"
    return s

def yi(tf: str) -> str:
    return {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"60m","4h":"60m","1d":"1d"}.get(tf,"15m")

def resample(rows: list[dict], width: int = 14_400_000) -> list[dict]:
    buckets: dict[int, list] = {}
    for r in rows:
        buckets.setdefault(int(r["ts"])//width*width, []).append(r)
    return [{"ts": k, "open": g[0]["open"], "high": max(z["high"] for z in g),
             "low": min(z["low"] for z in g), "close": g[-1]["close"]}
            for k, g in sorted(buckets.items())]

async def yahoo(symbol: str, tf: str, days: int) -> list[dict]:
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    iv    = yi(tf)
    if iv in {"1m","5m","15m","30m","60m"}:
        start = max(start, end - timedelta(days=59))
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as c:
        r = await c.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol(symbol)}",
                        params={"period1": int(start.timestamp()), "period2": int(end.timestamp()),
                                "interval": iv, "events": "history"})
    r.raise_for_status()
    res = r.json().get("chart", {}).get("result", [None])[0]
    if not res: raise RuntimeError("No data from Yahoo Finance")
    q = res["indicators"]["quote"][0]
    rows = []
    for i, ts in enumerate(res.get("timestamp", [])):
        try:
            rows.append({"ts": int(ts)*1000, "open": float(q["open"][i]),
                         "high": float(q["high"][i]), "low": float(q["low"][i]),
                         "close": float(q["close"][i]), "volume": float((q.get("volume") or [0])[i] or 0)})
        except Exception: pass
    return resample(rows) if tf == "4h" else rows

async def mt5_data(uid: str, sid: str, s: dict) -> list[dict]:
    now = datetime.now(timezone.utc)
    payload = {"user_id": uid, "strategy_id": sid, "symbol": s["symbol"],
               "timeframe": s["timeframe"], "job_type": "market_data",
               "date_from": (now - timedelta(days=s.get("lookback_days",90))).isoformat(),
               "date_to": now.isoformat(), "status": "queued"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{SB}/rest/v1/mt5_bridge_jobs", headers=sh(), json=payload)
    if not r.is_success: raise RuntimeError("Could not queue MT5 data request")
    job_id = r.json()[0]["id"]
    deadline = asyncio.get_running_loop().time() + 90
    while asyncio.get_running_loop().time() < deadline:
        async with httpx.AsyncClient(timeout=10) as c:
            jr = await c.get(f"{SB}/rest/v1/mt5_bridge_jobs", headers=sh(),
                             params={"id": f"eq.{job_id}", "select": "status,rates,error", "limit": "1"})
        row = jr.json()[0] if jr.is_success and jr.json() else None
        if row and row["status"] == "complete":
            return [{"ts": int(x.get("time",x.get("ts",0)))*1000 if x.get("time") else int(x.get("ts",0)),
                     "open": float(x["open"]), "high": float(x["high"]),
                     "low": float(x["low"]),  "close": float(x["close"]),
                     "volume": float(x.get("tick_volume", x.get("volume", 0)))}
                    for x in (row.get("rates") or [])]
        if row and row["status"] == "failed":
            raise RuntimeError(row.get("error") or "MT5 data request failed")
        await asyncio.sleep(2)
    raise RuntimeError("MT5 timed out")

async def _get_rows(uid: str, sid: str, s: dict) -> tuple[list[dict], str]:
    try:
        rows = await mt5_data(uid, sid, s)
        if rows: return rows, "MT5"
    except Exception as e:
        log.warning("MT5 data failed, trying Yahoo: %s", e)
    try:
        rows = await yahoo(s["symbol"], s["timeframe"], s.get("lookback_days", 90))
        if rows: return rows, "Yahoo Finance"
    except Exception as e:
        log.warning("Yahoo Finance failed: %s", e)
    raise RuntimeError(
        "Market data is temporarily unavailable. Open MetaTrader 5 and start the bridge app, then retry.")

# ── Pipeline stages ───────────────────────────────────────────────────────────

async def run_research(strategy_id: str, user_id: str, token: str) -> None:
    try:
        strategy = await load(strategy_id, user_id, token)
        state    = strategy.get("spec") or {}
        raw      = strategy.get("raw_strategy_text") or ""

        # Use v2 compiled spec if available, else parse raw text
        spec = (state.get("runtime") or state.get("parsed_strategy") or _parse(raw))
        state["parsed_strategy"] = spec
        state["runtime"]         = spec
        state["research_criteria"] = _criteria(spec)
        state["pipeline_stage"]    = "research_running"
        state["pending_confirmation"] = None
        state.setdefault("agents", {})
        state["agents"].update({"research": "running", "backtest": "gated",
                                 "indicator": "gated", "risk": "gated", "live": "gated"})
        _act(state, "Research Agent running",
             f"Fetching {spec.get('symbol','?')} {spec.get('timeframe','?')} bars…", "running")
        await save(strategy_id, user_id, token, state, "research_running")

        rows, source = await _get_rows(user_id, strategy_id, spec)
        closes = [float(x["close"]) for x in rows]
        rr     = rsi_calc(closes, spec.get("rsi_period", 14))
        bands  = bb_calc(closes, spec.get("bollinger_period", 20), spec.get("bollinger_std", 2.0))
        valid  = sum(1 for i in range(len(rows)) if rr[i] is not None and bands[i])
        entries = sum(1 for i in range(len(rows))
                      if rr[i] is not None and bands[i]
                      and rr[i] < spec.get("rsi_entry_below", 30)
                      and float(rows[i].get("low", rows[i]["close"])) <= bands[i][1])

        state.update({
            "data_source": source, "bars_loaded": len(rows),
            "research": {"status": "complete", "bars_checked": len(rows),
                         "indicator_ready_bars": valid, "entry_candidates": entries,
                         "data_source": source},
            "pipeline_stage": "research_complete",
            "pending_confirmation": "backtest",
        })
        state["agents"].update({"research": "complete", "backtest": "gated"})
        _act(state, "Research complete",
             f"{len(rows):,} bars from {source} · {entries:,} entry candidates found")
        await save(strategy_id, user_id, token, state, "research_complete")
        log.info("Research complete sid=%s source=%s bars=%d entries=%d",
                 strategy_id[:8], source, len(rows), entries)

    except Exception as exc:
        log.exception("Research failed sid=%s", strategy_id)
        try:
            state = (await load(strategy_id, user_id, token)).get("spec") or {}
            state["pipeline_stage"] = "research_failed"
            state["error"] = "Research couldn't complete. Make sure MetaTrader 5 is open, then type 'yes' to retry."
            state.setdefault("agents", {})["research"] = "failed"
            _act(state, "Research failed", str(exc)[:200], "failed")
            await save(strategy_id, user_id, token, state, "research_failed")
        except Exception: pass

async def run_backtest(strategy_id: str, user_id: str, token: str) -> None:
    try:
        strategy = await load(strategy_id, user_id, token)
        state    = strategy.get("spec") or {}
        spec     = state.get("runtime") or state.get("parsed_strategy") or _parse(strategy.get("raw_strategy_text",""))

        state["pipeline_stage"] = "backtest_running"
        state["pending_confirmation"] = None
        state.setdefault("agents", {})
        state["agents"].update({"research":"complete","backtest":"running",
                                 "indicator":"gated","risk":"gated","live":"gated"})
        _act(state, "Backtest running",
             f"Testing {spec.get('symbol','?')} {spec.get('timeframe','?')} against real historical data…", "running")
        await save(strategy_id, user_id, token, state, "backtesting")

        rows, source = await _get_rows(user_id, strategy_id, spec)
        result = run_bt(rows, spec)
        m = result["metrics"]

        state.update({
            "data_source": source, "bars_loaded": len(rows),
            "backtest": {**result, "symbol": spec.get("symbol"), "timeframe": spec.get("timeframe"),
                         "period_days": spec.get("lookback_days", 90), "data_source": source},
            "backtest_criteria": _criteria(spec),
            "pipeline_stage": "backtest_complete",
            "pending_confirmation": None,
        })
        state["agents"].update({"research":"complete","backtest":"complete",
                                  "indicator":"gated","risk":"gated","live":"gated"})
        _act(state, "Backtest complete",
             f"{m['trade_count']} trades · {m['win_rate']}% win rate · "
             f"{m['total_return_pct']}% return · {m['max_drawdown_pct']}% max DD")
        await save(strategy_id, user_id, token, state, "backtest_complete")
        log.info("Backtest complete sid=%s trades=%d wr=%.1f",
                 strategy_id[:8], m["trade_count"], m["win_rate"])

    except Exception as exc:
        log.exception("Backtest failed sid=%s", strategy_id)
        try:
            state = (await load(strategy_id, user_id, token)).get("spec") or {}
            state["pipeline_stage"] = "backtest_failed"
            state["error"] = "Backtest couldn't complete. Make sure MetaTrader 5 is open, then type 'yes' to retry."
            state.setdefault("agents", {})["backtest"] = "failed"
            _act(state, "Backtest failed", str(exc)[:200], "failed")
            await save(strategy_id, user_id, token, state, "backtest_failed")
        except Exception: pass

async def run_pipeline(strategy_id: str, user_id: str, token: str) -> None:
    await run_research(strategy_id, user_id, token)

@api_router.get("/status/{strategy_id}")
async def status(strategy_id: str, user=Depends(get_current_user)):
    token = user.get("_access_token") or user.get("access_token")
    if not token:
        raise HTTPException(401, "Session expired")
    try:
        strategy = await load(strategy_id, user["id"], token)
        state = strategy.get("spec") or {}
        return {"strategy_id": strategy_id, "status": strategy.get("status"),
                "pipeline_stage": state.get("pipeline_stage"),
                "agents": state.get("agents", {}),
                "activity": state.get("activity", [])[-10:],
                "research": state.get("research"),
                "backtest": state.get("backtest"),
                "error": state.get("error")}
    except Exception:
        raise HTTPException(500, "Status unavailable")
