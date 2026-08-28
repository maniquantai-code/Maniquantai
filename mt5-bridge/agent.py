"""ManiQuantAI Windows MT5 bridge with deterministic live strategy scanning.

The agent runs on the user's Windows machine beside MetaTrader 5. After an
explicit live approval, it polls the bridge for approved strategies, reads
live MT5 candles, evaluates the stored deterministic strategy conditions, and
queues validated signals for execution. The server remains the authority for
live approval and execution authorization.
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any

import httpx
import MetaTrader5 as mt5

API = os.environ["MANIQUANT_API"].rstrip("/")
TOKEN = os.environ["MT5_BRIDGE_TOKEN"]
POLL_SECONDS = float(os.getenv("MT5_BRIDGE_POLL_SECONDS", "2"))


def api_get(path: str, **params: Any) -> dict:
    with httpx.Client(timeout=20) as c:
        r = c.get(f"{API}{path}", params=params, headers={"Authorization": f"Bearer {TOKEN}"})
        r.raise_for_status()
        return r.json()


def api_post(path: str, payload: dict) -> dict:
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{API}{path}", json=payload, headers={"Authorization": f"Bearer {TOKEN}"})
        r.raise_for_status()
        return r.json()


def initialize() -> None:
    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")
    if login and password and server:
        if not mt5.initialize(login=int(login), password=password, server=server):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        return
    if not mt5.initialize():
        raise RuntimeError(f"MT5 terminal is not available: {mt5.last_error()}")


def market_data(job: dict) -> None:
    symbol = str(job["symbol"]).upper()
    timeframe = {"1m": mt5.TIMEFRAME_M1,"5m": mt5.TIMEFRAME_M5,"15m": mt5.TIMEFRAME_M15,"30m": mt5.TIMEFRAME_M30,"1h": mt5.TIMEFRAME_H1,"4h": mt5.TIMEFRAME_H4,"1d": mt5.TIMEFRAME_D1,"1w": mt5.TIMEFRAME_W1}.get(job["timeframe"], mt5.TIMEFRAME_M15)
    if not mt5.symbol_select(symbol, True): raise RuntimeError(f"MT5 symbol is unavailable: {symbol}")
    import datetime as dt
    start = dt.datetime.fromisoformat(job["date_from"].replace("Z", "+00:00")); end = dt.datetime.fromisoformat(job["date_to"].replace("Z", "+00:00"))
    rates = mt5.copy_rates_range(symbol, timeframe, start, end)
    if rates is None or len(rates) == 0: raise RuntimeError(f"No MT5 market data for {symbol} {job['timeframe']}")
    rows = [{"time": int(x["time"]),"open": float(x["open"]),"high": float(x["high"]),"low": float(x["low"]),"close": float(x["close"]),"tick_volume": int(x["tick_volume"])} for x in rates]
    api_post(f"/api/mt5-bridge/jobs/{job['id']}/complete", {"job_id": job["id"],"rates": rows,"account": account_snapshot()})


def account_snapshot() -> dict:
    info = mt5.account_info()
    if info is None: return {}
    return {"login": int(info.login),"server": str(info.server),"currency": str(info.currency),"balance": float(info.balance),"equity": float(info.equity),"margin_free": float(info.margin_free)}


def rsi(values: list[float], period: int) -> list[float | None]:
    out=[None]*len(values)
    if len(values)<=period: return out
    gains=[max(values[i]-values[i-1],0.0) for i in range(1,len(values))]
    losses=[max(values[i-1]-values[i],0.0) for i in range(1,len(values))]
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for i in range(period,len(values)):
        if i>period:
            ag=(ag*(period-1)+gains[i-1])/period; al=(al*(period-1)+losses[i-1])/period
        out[i]=100.0 if al==0 else 100.0-100.0/(1.0+ag/al)
    return out


def bollinger(values: list[float], period: int, std_mult: float) -> list[tuple[float,float,float] | None]:
    out=[None]*len(values)
    for i in range(period-1,len(values)):
        w=values[i-period+1:i+1]; mean=sum(w)/period
        sd=(sum((x-mean)**2 for x in w)/period)**0.5
        out[i]=(mean,mean-std_mult*sd,mean+std_mult*sd)
    return out


def timeframe_value(tf: str):
    return {"1m":mt5.TIMEFRAME_M1,"5m":mt5.TIMEFRAME_M5,"15m":mt5.TIMEFRAME_M15,"30m":mt5.TIMEFRAME_M30,"1h":mt5.TIMEFRAME_H1,"4h":mt5.TIMEFRAME_H4,"1d":mt5.TIMEFRAME_D1}.get(tf,mt5.TIMEFRAME_M15)


def open_positions(symbol: str):
    positions=mt5.positions_get(symbol=symbol)
    return list(positions or [])


def evaluate_strategy(strategy: dict) -> dict | None:
    sid=strategy["strategy_id"]; spec=strategy.get("spec") or {}; parsed=spec.get("parsed_strategy") or {}
    symbol=str(parsed.get("symbol") or spec.get("symbol") or "").upper(); tf=str(parsed.get("timeframe") or spec.get("timeframe") or "15m")
    if not symbol: return None
    if not mt5.symbol_select(symbol,True): return None
    rates=mt5.copy_rates_from_pos(symbol,timeframe_value(tf),0,120)
    if rates is None or len(rates)<30: return None
    # Only evaluate the last completed candle. This prevents repeated signals
    # while the current candle is still forming.
    idx=len(rates)-2
    closes=[float(x["close"]) for x in rates]; lows=[float(x["low"]) for x in rates]
    rp=int(parsed.get("rsi_period",14)); bp=int(parsed.get("bollinger_period",20)); bs=float(parsed.get("bollinger_std",2)); entry_rsi=float(parsed.get("rsi_entry_below",30)); exit_rsi=float(parsed.get("rsi_exit_above",55))
    rr=rsi(closes,rp); bb=bollinger(closes,bp,bs)
    if rr[idx] is None or bb[idx] is None: return None
    candle_time=int(rates[idx]["time"]); positions=open_positions(symbol)
    has_long=any(int(p.type)==mt5.POSITION_TYPE_BUY for p in positions)
    # Long entry: exact deterministic rule compiled by the strategy pipeline.
    if not positions and rr[idx] < entry_rsi and lows[idx] <= bb[idx][1]:
        volume=float(parsed.get("volume") or spec.get("live_config",{}).get("volume") or 0)
        sl=float(parsed.get("stop_loss") or spec.get("live_config",{}).get("stop_loss") or 0)
        tp=float(parsed.get("take_profit") or spec.get("live_config",{}).get("take_profit") or 0)
        if volume<=0:
            print(f"Signal detected for {sid}, but no explicit execution volume is configured; order blocked.")
            return None
        return {"strategy_id":sid,"symbol":symbol,"timeframe":tf,"side":"buy","volume":volume,"stop_loss":sl or None,"take_profit":tp or None,"risk_percent":float(parsed.get("risk_pct",0) or 0),"reason":f"RSI {rr[idx]:.2f} < {entry_rsi:g} and candle low touched lower Bollinger Band","signal_key":f"{sid}:{candle_time}:buy"}
    # Exit: close the existing long position rather than opening a new short.
    if has_long and rr[idx] >= exit_rsi:
        p=next(p for p in positions if int(p.type)==mt5.POSITION_TYPE_BUY)
        return {"strategy_id":sid,"symbol":symbol,"timeframe":tf,"side":"close_buy","volume":float(p.volume),"stop_loss":None,"take_profit":None,"risk_percent":0,"reason":f"RSI {rr[idx]:.2f} >= {exit_rsi:g}","signal_key":f"{sid}:{candle_time}:close_buy"}
    return None


def scan_live() -> None:
    data=api_get("/api/mt5-bridge/live-strategies")
    for strategy in data.get("strategies",[]):
        try:
            signal=evaluate_strategy(strategy)
            if signal:
                result=api_post("/api/mt5-bridge/live-signal",signal)
                print("Live signal:",strategy.get("name"),result)
        except Exception as exc:
            print("Live strategy scan failed:",strategy.get("strategy_id"),exc)


def execute(job: dict) -> None:
    req=job.get("request") or {}; symbol=str(req["symbol"]).upper(); side=str(req["side"]).lower()
    if not mt5.symbol_select(symbol,True): raise RuntimeError(f"MT5 symbol is unavailable: {symbol}")
    positions=open_positions(symbol)
    if side in {"close_buy","close_sell","close"}:
        targets=positions if side=="close" else [p for p in positions if (side=="close_buy" and int(p.type)==mt5.POSITION_TYPE_BUY) or (side=="close_sell" and int(p.type)==mt5.POSITION_TYPE_SELL)]
        for p in targets:
            tick=mt5.symbol_info_tick(symbol)
            if tick is None: raise RuntimeError(f"Could not read live price for {symbol}")
            close_type=mt5.ORDER_TYPE_SELL if int(p.type)==mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price=float(tick.bid if int(p.type)==mt5.POSITION_TYPE_BUY else tick.ask)
            request={"action":mt5.TRADE_ACTION_DEAL,"symbol":symbol,"volume":float(p.volume),"type":close_type,"position":int(p.ticket),"price":price,"deviation":int(req.get("deviation",20)),"magic":int(req.get("magic",260821)),"comment":str(req.get("comment","ManiQuantAI"))[:31],"type_time":mt5.ORDER_TIME_GTC,"type_filling":getattr(mt5.symbol_info(symbol),"filling_mode",mt5.ORDER_FILLING_IOC)}
            result=mt5.order_send(request)
            if result is None or result.retcode!=mt5.TRADE_RETCODE_DONE: raise RuntimeError(f"MT5 close rejected: {getattr(result,'retcode',None)} {getattr(result,'comment','')}")
        api_post(f"/api/mt5-bridge/execution/{job['id']}/complete",{"job_id":job["id"],"result":{"status":"closed","symbol":symbol,"account":account_snapshot()}}); return
    if side not in {"buy","sell"}: raise RuntimeError(f"Unsupported execution side: {side}")
    tick=mt5.symbol_info_tick(symbol); info=mt5.symbol_info(symbol)
    if tick is None or info is None: raise RuntimeError(f"Could not read live price for {symbol}")
    volume=float(req["volume"]); price=float(tick.ask if side=="buy" else tick.bid); order_type=mt5.ORDER_TYPE_BUY if side=="buy" else mt5.ORDER_TYPE_SELL
    request={"action":mt5.TRADE_ACTION_DEAL,"symbol":symbol,"volume":volume,"type":order_type,"price":price,"sl":float(req.get("stop_loss",0) or 0),"tp":float(req.get("take_profit",0) or 0),"deviation":int(req.get("deviation",20)),"magic":int(req.get("magic",260821)),"comment":str(req.get("comment","ManiQuantAI"))[:31],"type_time":mt5.ORDER_TIME_GTC,"type_filling":getattr(info,"filling_mode",mt5.ORDER_FILLING_IOC)}
    check=mt5.order_check(request)
    if check is None: raise RuntimeError("MT5 order_check failed")
    result=mt5.order_send(request)
    if result is None or result.retcode!=mt5.TRADE_RETCODE_DONE: raise RuntimeError(f"MT5 rejected live order: {getattr(result,'retcode',None)} {getattr(result,'comment','')}")
    api_post(f"/api/mt5-bridge/execution/{job['id']}/complete",{"job_id":job["id"],"result":{"retcode":int(result.retcode),"order":int(result.order),"deal":int(result.deal),"volume":float(result.volume),"price":float(result.price),"comment":str(result.comment),"account":account_snapshot()}})


def main() -> None:
    initialize(); print("ManiQuantAI MT5 bridge connected; live scanner enabled")
    try:
        last_scan=0.0
        while True:
            now=time.time()
            if now-last_scan>=POLL_SECONDS:
                try: api_post("/api/mt5-bridge/heartbeat",{"symbol":"","bid":0,"ask":0,"account_login":int(mt5.account_info().login) if mt5.account_info() else 0,"server":str(mt5.account_info().server) if mt5.account_info() else ""})
                except Exception as exc: print("Heartbeat failed:",exc)
                try: scan_live()
                except Exception as exc: print("Live scan unavailable:",exc)
                last_scan=now
            try:
                data=api_get("/api/mt5-bridge/jobs")
                for job in data.get("jobs",[]):
                    try:
                        if job.get("job_type","market_data")=="execution": execute(job)
                        else: market_data(job)
                    except Exception as exc:
                        try:
                            if job.get("job_type","market_data")=="execution": api_post(f"/api/mt5-bridge/execution/{job['id']}/fail",{"job_id":job["id"],"error":str(exc)[:1000]})
                            else: api_post(f"/api/mt5-bridge/jobs/{job['id']}/fail",{"job_id":job["id"],"error":str(exc)[:1000]})
                        except Exception as report_exc: print("Could not report bridge failure:",report_exc)
            except Exception as exc: print("Job polling failed:",exc)
            time.sleep(POLL_SECONDS)
    finally: mt5.shutdown()


if __name__=="__main__": main()
