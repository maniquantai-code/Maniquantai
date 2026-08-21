"""ManiQuantAI Windows MT5 bridge.

Run this process on the Windows PC where the user's MetaTrader 5 terminal is
installed and logged in. It never exposes MT5 directly to the internet; it
polls the authenticated ManiQuantAI HTTPS bridge API and executes only signed
jobs that have already passed the server-side live-approval gate.

Environment:
  MANIQUANT_API=https://<your-api>
  MT5_BRIDGE_TOKEN=<token returned by /api/mt5-bridge/register>
  MT5_LOGIN / MT5_PASSWORD / MT5_SERVER are optional when the terminal is
  already logged in. If omitted, the agent bootstraps encrypted credentials
  once from the bridge and initializes MT5 locally.
"""
from __future__ import annotations

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
        r = c.get(f"{API}{path}", params={"token": TOKEN, **params})
        r.raise_for_status()
        return r.json()


def api_post(path: str, payload: dict) -> dict:
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{API}{path}", json={"token": TOKEN, **payload})
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
    # The terminal can already be logged in. In that mode no credentials are
    # copied into the bridge process or sent back to the cloud.
    if not mt5.initialize():
        raise RuntimeError(f"MT5 terminal is not available: {mt5.last_error()}")


def market_data(job: dict) -> None:
    symbol = str(job["symbol"]).upper()
    timeframe = {
        "1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5,
        "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4,
        "1d": mt5.TIMEFRAME_D1, "1w": mt5.TIMEFRAME_W1,
    }.get(job["timeframe"], mt5.TIMEFRAME_M15)
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"MT5 symbol is unavailable: {symbol}")
    import datetime as dt
    start = dt.datetime.fromisoformat(job["date_from"].replace("Z", "+00:00"))
    end = dt.datetime.fromisoformat(job["date_to"].replace("Z", "+00:00"))
    rates = mt5.copy_rates_range(symbol, timeframe, start, end)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No MT5 market data for {symbol} {job['timeframe']}")
    rows = [{
        "time": int(x["time"]), "open": float(x["open"]),
        "high": float(x["high"]), "low": float(x["low"]),
        "close": float(x["close"]), "tick_volume": int(x["tick_volume"]),
    } for x in rates]
    api_post(f"/api/mt5-bridge/jobs/{job['id']}/complete", {
        "job_id": job["id"], "rates": rows,
        "account": account_snapshot(),
    })


def account_snapshot() -> dict:
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "login": int(info.login), "server": str(info.server),
        "currency": str(info.currency), "balance": float(info.balance),
        "equity": float(info.equity), "margin_free": float(info.margin_free),
    }


def execute(job: dict) -> None:
    req = job.get("request") or {}
    symbol = str(req["symbol"]).upper()
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"MT5 symbol is unavailable: {symbol}")
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        raise RuntimeError(f"Could not read live price for {symbol}")

    side = req["side"].lower()
    volume = float(req["volume"])
    price = float(tick.ask if side == "buy" else tick.bid)
    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    filling = getattr(info, "filling_mode", mt5.ORDER_FILLING_IOC)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": float(req.get("stop_loss", 0) or 0),
        "tp": float(req.get("take_profit", 0) or 0),
        "deviation": int(req.get("deviation", 20)),
        "magic": int(req.get("magic", 260821)),
        "comment": str(req.get("comment", "ManiQuantAI"))[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }
    check = mt5.order_check(request)
    if check is None or getattr(check, "retcode", 0) not in (0, mt5.TRADE_RETCODE_DONE):
        # order_check may use broker-specific retcodes; the actual order is
        # still the final authority, but an explicit invalid request is fatal.
        comment = getattr(check, "comment", "order_check failed") if check else "order_check failed"
        if check is not None and getattr(check, "retcode", 0) not in (0, mt5.TRADE_RETCODE_DONE):
            raise RuntimeError(f"MT5 order check rejected request: {comment}")
    result = mt5.order_send(request)
    if result is None:
        raise RuntimeError(f"MT5 order_send failed: {mt5.last_error()}")
    payload = {
        "retcode": int(result.retcode), "order": int(result.order),
        "deal": int(result.deal), "volume": float(result.volume),
        "price": float(result.price), "comment": str(result.comment),
        "account": account_snapshot(),
    }
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"MT5 rejected live order: {result.retcode} {result.comment}")
    api_post(f"/api/mt5-bridge/execution/{job['id']}/complete", {
        "job_id": job["id"], "result": payload,
    })


def main() -> None:
    initialize()
    print("ManiQuantAI MT5 bridge connected")
    try:
        while True:
            data = api_get("/api/mt5-bridge/jobs")
            for job in data.get("jobs", []):
                try:
                    if job.get("job_type", "market_data") == "execution":
                        execute(job)
                    else:
                        market_data(job)
                except Exception as exc:
                    try:
                        if job.get("job_type", "market_data") == "execution":
                            api_post(f"/api/mt5-bridge/execution/{job['id']}/fail", {"job_id": job["id"], "error": str(exc)[:1000]})
                        else:
                            api_post(f"/api/mt5-bridge/jobs/{job['id']}/fail", {"job_id": job["id"], "error": str(exc)[:1000]})
                    except Exception as report_exc:
                        print("Could not report bridge failure:", report_exc)
            time.sleep(POLL_SECONDS)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
