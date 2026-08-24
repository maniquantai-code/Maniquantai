"""ManiQuantAI Windows MT5 bridge.

Run this process on the same Windows PC as the logged-in MetaTrader 5 terminal.
It polls the authenticated cloud bridge and executes only server-approved jobs.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any

import MetaTrader5 as mt5
import requests

API = os.environ["MANIQUANT_API_URL"].rstrip("/")
TOKEN = os.environ["MT5_BRIDGE_TOKEN"]
POLL = float(os.getenv("MT5_BRIDGE_POLL_SECONDS", "2"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _post(path: str, payload: dict[str, Any], timeout: int = 30):
    r = requests.post(f"{API}{path}", json={"token": TOKEN, **payload}, timeout=timeout)
    r.raise_for_status()
    return r


def rates(job: dict[str, Any]):
    symbol = job["symbol"].upper()
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"MT5 symbol unavailable: {symbol}")
    tf = getattr(mt5, job.get("timeframe", "TIMEFRAME_M15"), mt5.TIMEFRAME_M15)
    data = mt5.copy_rates_range(
        symbol,
        tf,
        datetime.fromisoformat(job["date_from"].replace("Z", "+00:00")),
        datetime.fromisoformat(job["date_to"].replace("Z", "+00:00")),
    )
    if data is None or len(data) == 0:
        raise RuntimeError(f"MT5 rates failed: {mt5.last_error()}")
    return [{
        "time": int(x["time"]),
        "open": float(x["open"]),
        "high": float(x["high"]),
        "low": float(x["low"]),
        "close": float(x["close"]),
        "tick_volume": int(x["tick_volume"]),
    } for x in data]


def account():
    a = mt5.account_info()
    t = mt5.terminal_info()
    return {
        "login": int(a.login) if a else None,
        "server": str(a.server) if a else None,
        "currency": str(a.currency) if a else None,
        "balance": float(a.balance) if a else None,
        "equity": float(a.equity) if a else None,
        "margin_free": float(a.margin_free) if a else None,
        "terminal_connected": bool(t and t.connected),
    }


def execute(job: dict[str, Any]):
    req = job.get("request") or {}
    symbol = str(req["symbol"]).upper()
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"MT5 symbol unavailable: {symbol}")
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        raise RuntimeError(f"Could not read live price for {symbol}")
    side = str(req["side"]).lower()
    if side not in {"buy", "sell"}:
        raise RuntimeError("Order side must be buy or sell")
    volume = float(req["volume"])
    price = float(tick.ask if side == "buy" else tick.bid)
    filling = getattr(info, "filling_mode", mt5.ORDER_FILLING_IOC)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
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
    if check is not None and getattr(check, "retcode", 0) not in (0, mt5.TRADE_RETCODE_DONE):
        raise RuntimeError(f"MT5 order check rejected request: {getattr(check, 'comment', 'unknown')}")
    result = mt5.order_send(request)
    if result is None:
        raise RuntimeError(f"MT5 order_send failed: {mt5.last_error()}")
    payload = {
        "retcode": int(result.retcode),
        "order": int(result.order),
        "deal": int(result.deal),
        "volume": float(result.volume),
        "price": float(result.price),
        "comment": str(result.comment),
        "account": account(),
    }
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"MT5 rejected live order: {result.retcode} {result.comment}")
    _post(f"/api/mt5-bridge/execution/{job['id']}/complete", {"job_id": job["id"], "result": payload})
    logging.info("MT5 execution complete: %s", payload)


def complete_market_data(job: dict[str, Any]):
    _post(f"/api/mt5-bridge/jobs/{job['id']}/complete", {
        "job_id": job["id"],
        "rates": rates(job),
        "account": account(),
    })


def main():
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    logging.info("ManiQuantAI MT5 bridge connected")
    try:
        while True:
            try:
                r = requests.get(f"{API}/api/mt5-bridge/jobs", params={"token": TOKEN}, timeout=15)
                r.raise_for_status()
                jobs = r.json().get("jobs", [])
                for job in jobs:
                    try:
                        if job.get("job_type", "market_data") == "execution":
                            execute(job)
                        else:
                            complete_market_data(job)
                    except Exception as exc:
                        logging.exception("Job %s failed", job.get("id"))
                        try:
                            if job.get("job_type", "market_data") == "execution":
                                _post(f"/api/mt5-bridge/execution/{job['id']}/fail", {"job_id": job["id"], "error": str(exc)[:1000]}, 15)
                            else:
                                _post(f"/api/mt5-bridge/jobs/{job['id']}/fail", {"job_id": job["id"], "error": str(exc)[:1000]}, 15)
                        except Exception:
                            logging.exception("Could not report bridge failure")
            except Exception as exc:
                logging.warning("Bridge poll: %s", exc)
            time.sleep(POLL)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
