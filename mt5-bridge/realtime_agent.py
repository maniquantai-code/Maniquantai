"""ManiQuantAI realtime MT5 bridge.

Runs beside the user's MetaTrader 5 terminal. The bridge owns broker I/O;
the ManiQuantAI API remains authoritative for approval, risk and execution
authorization. Strategy evaluation is deterministic and uses the compiled
Strategy Spec; LLM output is never sent directly to MT5.
"""
from __future__ import annotations
import os
import time
from typing import Any
import httpx
import MetaTrader5 as mt5

API = os.environ["MANIQUANT_API"].rstrip("/")
TOKEN = os.environ["MT5_BRIDGE_TOKEN"]
SCAN_SECONDS = max(0.2, float(os.getenv("MT5_BRIDGE_SCAN_SECONDS", "0.5")))
HEARTBEAT_SECONDS = max(1.0, float(os.getenv("MT5_BRIDGE_HEARTBEAT_SECONDS", "2")))
JOB_SECONDS = max(0.2, float(os.getenv("MT5_BRIDGE_JOB_SECONDS", "0.5")))
HTTP_TIMEOUT = float(os.getenv("MT5_BRIDGE_HTTP_TIMEOUT", "10"))
MAGIC = int(os.getenv("MT5_BRIDGE_MAGIC", "260821"))
DEVIATION = int(os.getenv("MT5_BRIDGE_DEVIATION", "20"))
TIMEFRAMES = {"1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30, "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1, "1w": mt5.TIMEFRAME_W1}

def client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(HTTP_TIMEOUT, connect=5), limits=httpx.Limits(max_connections=20, max_keepalive_connections=10), headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "ManiQuantAI-MT5-Bridge/2.1"})

def initialize_mt5() -> None:
    login, password, server = os.getenv("MT5_LOGIN"), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER")
    kwargs: dict[str, Any] = {"login": int(login), "password": password, "server": server} if login and password and server else {}
    if not mt5.initialize(**kwargs): raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

def ensure_mt5() -> None:
    if mt5.terminal_info() is None or mt5.account_info() is None:
        try: mt5.shutdown()
        except Exception: pass
        time.sleep(0.25); initialize_mt5()

def account_snapshot() -> dict[str, Any]:
    info = mt5.account_info()
    if info is None: return {}
    return {"login": int(info.login), "server": str(info.server), "currency": str(info.currency), "balance": float(info.balance), "equity": float(info.equity), "margin_free": float(info.margin_free), "trade_allowed": bool(info.trade_allowed)}

def post(c: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = c.post(f"{API}{path}", json=payload); r.raise_for_status(); return r.json()

def get(c: httpx.Client, path: str, **params: Any) -> dict[str, Any]:
    r = c.get(f"{API}{path}", params=params); r.raise_for_status(); return r.json()

def rsi(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period: return out
    gains = [max(values[i] - values[i-1], 0.0) for i in range(1, len(values))]; losses = [max(values[i-1] - values[i], 0.0) for i in range(1, len(values))]
    ag, al = sum(gains[:period]) / period, sum(losses[:period]) / period
    for i in range(period, len(values)):
        if i > period: ag = (ag*(period-1)+gains[i-1])/period; al = (al*(period-1)+losses[i-1])/period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0/(1.0 + ag/al)
    return out

def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period: return out
    value = sum(values[:period])/period; out[period-1] = value; alpha = 2.0/(period+1)
    for i in range(period, len(values)): value = alpha*values[i] + (1-alpha)*value; out[i] = value
    return out

def bollinger(values: list[float], period: int, mult: float):
    out = [None] * len(values)
    for i in range(period-1, len(values)):
        window = values[i-period+1:i+1]; mean = sum(window)/period; sd = (sum((x-mean)**2 for x in window)/period)**0.5; out[i] = (mean, mean-mult*sd, mean+mult*sd)
    return out

def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    ef, es = ema(values, fast), ema(values, slow); line = [None if ef[i] is None or es[i] is None else ef[i]-es[i] for i in range(len(values))]
    clean = [float(x) for x in line if x is not None]; sig_clean = ema(clean, signal); sig = [None]*len(values); j = 0
    for i, x in enumerate(line):
        if x is not None: sig[i] = sig_clean[j]; j += 1
    return line, sig

def positions(symbol: str): return list(mt5.positions_get(symbol=symbol) or [])
def _runtime(strategy: dict[str, Any]) -> dict[str, Any]:
    spec = strategy.get("spec") or {}; parsed = spec.get("parsed_strategy") or spec; return parsed.get("runtime") or parsed

def _crossed_up(a, b, idx: int) -> bool:
    return idx > 0 and None not in (a[idx], b[idx], a[idx-1], b[idx-1]) and a[idx] > b[idx] and a[idx-1] <= b[idx-1]
def _crossed_down(a, b, idx: int) -> bool:
    return idx > 0 and None not in (a[idx], b[idx], a[idx-1], b[idx-1]) and a[idx] < b[idx] and a[idx-1] >= b[idx-1]

def _risk_volume(symbol: str, stop_distance: float, risk_pct: float) -> float:
    info, acct = mt5.symbol_info(symbol), mt5.account_info()
    if info is None or acct is None or stop_distance <= 0: return 0.0
    tick_size = float(getattr(info, "trade_tick_size", 0) or getattr(info, "point", 0) or 0); tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
    if tick_size <= 0 or tick_value <= 0: return 0.0
    loss_per_lot = stop_distance/tick_size*tick_value; raw = float(acct.equity)*min(max(risk_pct, 0), 2.0)/100.0/loss_per_lot
    vmin, vmax, step = float(info.volume_min), float(info.volume_max), float(info.volume_step or info.volume_min or 0.01)
    if raw < vmin: return 0.0
    return min(vmax, max(vmin, (raw//step)*step))

def evaluate(strategy: dict[str, Any]) -> dict[str, Any] | None:
    spec = strategy.get("spec") or {}; parsed = spec.get("parsed_strategy") or spec; runtime = _runtime(strategy)
    symbol = str(parsed.get("symbol") or runtime.get("symbol") or "").upper(); tf = str(parsed.get("timeframe") or runtime.get("timeframe") or "15m"); stype = str(parsed.get("strategy_type") or spec.get("strategy_type") or "multi_signal")
    if not symbol or tf not in TIMEFRAMES or not mt5.symbol_select(symbol, True): return None
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[tf], 0, 220)
    if rates is None or len(rates) < 60: return None
    idx = len(rates)-2; closes = [float(x["close"]) for x in rates]; highs = [float(x["high"]) for x in rates]; lows = [float(x["low"]) for x in rates]; ps = positions(symbol); candle = int(rates[idx]["time"]); sid = strategy["strategy_id"]
    has_long = any(int(p.type) == mt5.POSITION_TYPE_BUY for p in ps); has_short = any(int(p.type) == mt5.POSITION_TYPE_SELL for p in ps)
    long_entry = short_entry = False; reason = ""
    if stype == "rsi_bollinger":
        rr, bb = rsi(closes, int(runtime.get("rsi_period",14))), bollinger(closes, int(runtime.get("bollinger_period",20)), float(runtime.get("bollinger_std",2)))
        if rr[idx] is None or bb[idx] is None: return None
        long_entry = rr[idx] < float(runtime.get("rsi_entry_below",30)) and lows[idx] <= bb[idx][1]; short_entry = rr[idx] > float(runtime.get("rsi_entry_above",70)) and highs[idx] >= bb[idx][2]; reason = f"RSI {rr[idx]:.2f} with Bollinger touch"
        if has_long and rr[idx] >= float(runtime.get("rsi_exit_above",55)):
            p = next(p for p in ps if int(p.type)==mt5.POSITION_TYPE_BUY); return {"strategy_id":sid,"symbol":symbol,"timeframe":tf,"side":"close_buy","volume":float(p.volume),"risk_percent":0,"reason":f"RSI {rr[idx]:.2f} exit","signal_key":f"{sid}:{candle}:close_buy"}
        if has_short and rr[idx] <= float(runtime.get("rsi_exit_below",55)):
            p = next(p for p in ps if int(p.type)==mt5.POSITION_TYPE_SELL); return {"strategy_id":sid,"symbol":symbol,"timeframe":tf,"side":"close_sell","volume":float(p.volume),"risk_percent":0,"reason":f"RSI {rr[idx]:.2f} exit","signal_key":f"{sid}:{candle}:close_sell"}
    elif stype == "ema_crossover":
        ef, es = ema(closes,int(runtime.get("ema_fast",9))), ema(closes,int(runtime.get("ema_slow",21))); long_entry, short_entry = _crossed_up(ef,es,idx), _crossed_down(ef,es,idx); reason="EMA crossover"
    elif stype == "macd":
        ml, sl = macd(closes); long_entry, short_entry = _crossed_up(ml,sl,idx), _crossed_down(ml,sl,idx); reason="MACD signal crossover"
    elif stype == "breakout":
        resistance, support = max(highs[idx-20:idx]), min(lows[idx-20:idx]); long_entry, short_entry = closes[idx] > resistance, closes[idx] < support; reason="20-bar breakout"
    elif stype == "scalping":
        ef, es = ema(closes,3), ema(closes,8); long_entry, short_entry = _crossed_up(ef,es,idx), _crossed_down(ef,es,idx); reason="EMA(3)/EMA(8) crossover"
    else: return None
    direction = str(parsed.get("direction") or runtime.get("direction") or "BOTH").upper()
    if direction == "LONG": short_entry = False
    if direction == "SHORT": long_entry = False
    if ps or not (long_entry or short_entry): return None
    tick, info = mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol)
    if tick is None or info is None: return None
    side = "buy" if long_entry else "sell"; entry = float(tick.ask if side=="buy" else tick.bid); risk_pct = float((parsed.get("risk") or {}).get("risk_pct_per_trade") or runtime.get("risk_pct") or 1.0)
    sl_cfg = runtime.get("stop_loss") or {}; stop_distance = 0.0
    if isinstance(sl_cfg,dict) and sl_cfg.get("type")=="ATR":
        period, mult = int(sl_cfg.get("period",14)), float(sl_cfg.get("multiplier",1.5)); trs=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])) for i in range(1,len(closes))]; stop_distance=sum(trs[-period:])/period*mult
    elif isinstance(sl_cfg,dict) and sl_cfg.get("type")=="PERCENT": stop_distance=entry*float(sl_cfg.get("value",0))/100
    else: stop_distance=float(sl_cfg or info.point*100)
    volume=float(runtime.get("volume") or spec.get("live_config",{}).get("volume") or 0) or _risk_volume(symbol,stop_distance,risk_pct)
    if volume<=0: return None
    sl_price = entry-stop_distance if side=="buy" else entry+stop_distance; tp_cfg=runtime.get("take_profit") or {}; tp_distance=stop_distance*float(tp_cfg.get("multiple",2)) if isinstance(tp_cfg,dict) and tp_cfg.get("type")=="R_MULTIPLE" else (entry*float(tp_cfg.get("value",0))/100 if isinstance(tp_cfg,dict) and tp_cfg.get("type")=="PERCENT" else stop_distance*2); tp_price=entry+tp_distance if side=="buy" else entry-tp_distance
    return {"strategy_id":sid,"symbol":symbol,"timeframe":tf,"side":side,"volume":volume,"stop_loss":sl_price,"take_profit":tp_price,"risk_percent":risk_pct,"reason":reason,"signal_key":f"{sid}:{candle}:{side}"}

def execute(c: httpx.Client, job: dict[str, Any]) -> None:
    req=job.get("request") or {}; symbol, side=str(req["symbol"]).upper(), str(req["side"]).lower()
    if not mt5.symbol_select(symbol,True): raise RuntimeError(f"MT5 symbol unavailable: {symbol}")
    tick, info=mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol)
    if tick is None or info is None: raise RuntimeError(f"No live tick for {symbol}")
    ps=positions(symbol)
    if side in {"close","close_buy","close_sell"}:
        targets=ps if side=="close" else [p for p in ps if (side=="close_buy" and int(p.type)==mt5.POSITION_TYPE_BUY) or (side=="close_sell" and int(p.type)==mt5.POSITION_TYPE_SELL)]
        for p in targets:
            close_type=mt5.ORDER_TYPE_SELL if int(p.type)==mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY; price=float(tick.bid if int(p.type)==mt5.POSITION_TYPE_BUY else tick.ask)
            order={"action":mt5.TRADE_ACTION_DEAL,"symbol":symbol,"volume":float(p.volume),"type":close_type,"position":int(p.ticket),"price":price,"deviation":int(req.get("deviation",DEVIATION)),"magic":MAGIC,"comment":str(req.get("comment","ManiQuantAI"))[:31],"type_time":mt5.ORDER_TIME_GTC,"type_filling":getattr(info,"filling_mode",mt5.ORDER_FILLING_IOC)}
            check=mt5.order_check(order)
            if check is None or getattr(check,"retcode",0) not in (0,mt5.TRADE_RETCODE_DONE): raise RuntimeError(f"MT5 close order_check rejected: {getattr(check,'retcode',None)} {getattr(check,'comment','')}")
            result=mt5.order_send(order)
            if result is None or result.retcode!=mt5.TRADE_RETCODE_DONE: raise RuntimeError(f"MT5 close rejected: {getattr(result,'retcode',None)} {getattr(result,'comment','')}")
        post(c,f"/api/mt5-bridge/execution/{job['id']}/complete",{"job_id":job["id"],"result":{"status":"closed","symbol":symbol,"account":account_snapshot()}}); return
    if side not in {"buy","sell"}: raise RuntimeError(f"Unsupported execution side: {side}")
    volume=float(req["volume"]); price=float(tick.ask if side=="buy" else tick.bid)
    if volume<=0: raise RuntimeError("Execution volume must be positive")
    max_spread_points=float(req.get("max_spread_points",os.getenv("MT5_MAX_SPREAD_POINTS","0")))
    if max_spread_points>0:
        spread_points=(float(tick.ask)-float(tick.bid))/float(info.point or 1)
        if spread_points>max_spread_points: raise RuntimeError(f"Spread {spread_points:.1f} points exceeds limit {max_spread_points:.1f}")
    order={"action":mt5.TRADE_ACTION_DEAL,"symbol":symbol,"volume":volume,"type":mt5.ORDER_TYPE_BUY if side=="buy" else mt5.ORDER_TYPE_SELL,"price":price,"sl":float(req.get("stop_loss") or 0),"tp":float(req.get("take_profit") or 0),"deviation":int(req.get("deviation",DEVIATION)),"magic":MAGIC,"comment":str(req.get("comment","ManiQuantAI"))[:31],"type_time":mt5.ORDER_TIME_GTC,"type_filling":getattr(info,"filling_mode",mt5.ORDER_FILLING_IOC)}
    check=mt5.order_check(order)
    if check is None or getattr(check,"retcode",0) not in (0,mt5.TRADE_RETCODE_DONE): raise RuntimeError(f"MT5 order_check rejected: {getattr(check,'retcode',None)} {getattr(check,'comment','')}")
    result=mt5.order_send(order)
    if result is None or result.retcode!=mt5.TRADE_RETCODE_DONE: raise RuntimeError(f"MT5 order rejected: {getattr(result,'retcode',None)} {getattr(result,'comment','')}")
    time.sleep(0.15); confirmed=positions(symbol)
    post(c,f"/api/mt5-bridge/execution/{job['id']}/complete",{"job_id":job["id"],"result":{"retcode":int(result.retcode),"order":int(result.order),"deal":int(result.deal),"volume":float(result.volume),"price":float(result.price),"comment":str(result.comment),"position_count_after":len(confirmed),"account":account_snapshot()}})

def main() -> None:
    initialize_mt5(); seen: dict[str,float]={}; last_scan=last_heartbeat=last_jobs=0.0
    with client() as c:
        print("ManiQuantAI realtime MT5 bridge online")
        while True:
            now=time.monotonic()
            try:
                ensure_mt5()
                if now-last_heartbeat>=HEARTBEAT_SECONDS:
                    acct=account_snapshot(); post(c,"/api/mt5-bridge/heartbeat",{"symbol":"","bid":0,"ask":0,"account_login":acct.get("login",0),"server":acct.get("server",""),"equity":acct.get("equity",0),"balance":acct.get("balance",0),"bridge_version":"2.1-realtime","scan_interval_ms":int(SCAN_SECONDS*1000)}); last_heartbeat=now
                if now-last_scan>=SCAN_SECONDS:
                    data=get(c,"/api/mt5-bridge/live-strategies")
                    for strategy in data.get("strategies",[]):
                        signal=evaluate(strategy)
                        if signal and signal["signal_key"] not in seen:
                            result=post(c,"/api/mt5-bridge/live-signal",signal); print("Signal:",strategy.get("name"),result); seen[signal["signal_key"]]=now
                    seen={k:t for k,t in seen.items() if now-t<86400}; last_scan=now
                if now-last_jobs>=JOB_SECONDS:
                    jobs=get(c,"/api/mt5-bridge/jobs")
                    for job in jobs.get("jobs",[]):
                        if job.get("job_type")!="execution": continue
                        try: execute(c,job)
                        except Exception as exc:
                            try: post(c,f"/api/mt5-bridge/execution/{job['id']}/fail",{"job_id":job["id"],"error":str(exc)[:1000]})
                            except Exception: pass
                    last_jobs=now
            except Exception as exc:
                print("Bridge loop warning:",exc); time.sleep(0.25)
            time.sleep(0.05)

if __name__=="__main__":
    try: main()
    finally: mt5.shutdown()
