"""ManiQuantAI realtime MT5 bridge.

Runs next to the user's MetaTrader 5 terminal. The bridge owns broker I/O;
the ManiQuantAI API remains the authority for strategy approval, risk gates,
and execution authorization. The agent uses persistent HTTP connections,
sub-second market scanning, heartbeat telemetry, reconnect handling, signal
deduplication, order_check, and post-trade verification.

This bridge deliberately evaluates deterministic rules locally. LLM output is
never executed directly.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
import MetaTrader5 as mt5

API = os.environ["MANIQUANT_API"].rstrip("/")
TOKEN = os.environ["MT5_BRIDGE_TOKEN"]
SCAN_SECONDS = float(os.getenv("MT5_BRIDGE_SCAN_SECONDS", "0.5"))
HEARTBEAT_SECONDS = float(os.getenv("MT5_BRIDGE_HEARTBEAT_SECONDS", "2"))
JOB_SECONDS = float(os.getenv("MT5_BRIDGE_JOB_SECONDS", "0.5"))
HTTP_TIMEOUT = float(os.getenv("MT5_BRIDGE_HTTP_TIMEOUT", "10"))
MAGIC = int(os.getenv("MT5_BRIDGE_MAGIC", "260821"))

TIMEFRAMES = {
    "1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15,
    "30m": mt5.TIMEFRAME_M30, "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4,
    "1d": mt5.TIMEFRAME_D1, "1w": mt5.TIMEFRAME_W1,
}


def client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(HTTP_TIMEOUT, connect=5),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "ManiQuantAI-MT5-Bridge/2.0"},
    )


def initialize_mt5() -> None:
    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")
    kwargs: dict[str, Any] = {}
    if login and password and server:
        kwargs = {"login": int(login), "password": password, "server": server}
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")


def ensure_mt5() -> None:
    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None or account is None:
        try:
            mt5.shutdown()
        except Exception:
            pass
        time.sleep(0.25)
        initialize_mt5()


def account_snapshot() -> dict[str, Any]:
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "login": int(info.login), "server": str(info.server), "currency": str(info.currency),
        "balance": float(info.balance), "equity": float(info.equity),
        "margin_free": float(info.margin_free), "trade_allowed": bool(info.trade_allowed),
    }


def post(c: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = c.post(f"{API}{path}", json=payload)
    r.raise_for_status()
    return r.json()


def get(c: httpx.Client, path: str, **params: Any) -> dict[str, Any]:
    r = c.get(f"{API}{path}", params=params)
    r.raise_for_status()
    return r.json()


def rsi(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    ag, al = sum(gains[:period]) / period, sum(losses[:period]) / period
    for i in range(period, len(values)):
        if i > period:
            ag = (ag * (period - 1) + gains[i - 1]) / period
            al = (al * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def bollinger(values: list[float], period: int, mult: float):
    out = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        mean = sum(window) / period
        sd = (sum((x - mean) ** 2 for x in window) / period) ** 0.5
        out[i] = (mean, mean - mult * sd, mean + mult * sd)
    return out


def positions(symbol: str):
    return list(mt5.positions_get(symbol=symbol) or [])


def evaluate(strategy: dict[str, Any]) -> dict[str, Any] | None:
    spec = strategy.get("spec") or {}
    parsed = spec.get("parsed_strategy") or {}
    symbol = str(parsed.get("symbol") or spec.get("symbol") or "").upper()
    tf = str(parsed.get("timeframe") or spec.get("timeframe") or "15m")
    if not symbol or tf not in TIMEFRAMES or not mt5.symbol_select(symbol, True):
        return None
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[tf], 0, 120)
    if rates is None or len(rates) < 30:
        return None
    idx = len(rates) - 2  # completed candle only
    closes = [float(x["close"]) for x in rates]
    lows = [float(x["low"]) for x in rates]
    rp = int(parsed.get("rsi_period", 14)); bp = int(parsed.get("bollinger_period", 20))
    bs = float(parsed.get("bollinger_std", 2)); entry = float(parsed.get("rsi_entry_below", 30))
    exit_level = float(parsed.get("rsi_exit_above", 55))
    rr, bb = rsi(closes, rp), bollinger(closes, bp, bs)
    if rr[idx] is None or bb[idx] is None:
        return None
    candle = int(rates[idx]["time"])
    ps = positions(symbol)
    has_long = any(int(p.type) == mt5.POSITION_TYPE_BUY for p in ps)
    sid = strategy["strategy_id"]
    if not ps and rr[idx] < entry and lows[idx] <= bb[idx][1]:
        volume = float(parsed.get("volume") or spec.get("live_config", {}).get("volume") or 0)
        sl = float(parsed.get("stop_loss") or spec.get("live_config", {}).get("stop_loss") or 0)
        tp = float(parsed.get("take_profit") or spec.get("live_config", {}).get("take_profit") or 0)
        if volume <= 0:
            return None
        return {"strategy_id": sid, "symbol": symbol, "timeframe": tf, "side": "buy", "volume": volume,
                "stop_loss": sl or None, "take_profit": tp or None, "risk_percent": float(parsed.get("risk_pct", 0) or 0),
                "reason": f"RSI {rr[idx]:.2f} < {entry:g} and completed candle touched lower Bollinger Band",
                "signal_key": f"{sid}:{candle}:buy"}
    if has_long and rr[idx] >= exit_level:
        p = next(p for p in ps if int(p.type) == mt5.POSITION_TYPE_BUY)
        return {"strategy_id": sid, "symbol": symbol, "timeframe": tf, "side": "close_buy", "volume": float(p.volume),
                "stop_loss": None, "take_profit": None, "risk_percent": 0,
                "reason": f"RSI {rr[idx]:.2f} >= {exit_level:g}", "signal_key": f"{sid}:{candle}:close_buy"}
    return None


def execute(c: httpx.Client, job: dict[str, Any]) -> None:
    req = job.get("request") or {}
    symbol, side = str(req["symbol"]).upper(), str(req["side"]).lower()
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"MT5 symbol unavailable: {symbol}")
    tick, info = mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol)
    if tick is None or info is None:
        raise RuntimeError(f"No live tick for {symbol}")
    ps = positions(symbol)
    if side in {"close", "close_buy", "close_sell"}:
        targets = ps if side == "close" else [p for p in ps if (side == "close_buy" and int(p.type) == mt5.POSITION_TYPE_BUY) or (side == "close_sell" and int(p.type) == mt5.POSITION_TYPE_SELL)]
        for p in targets:
            close_type = mt5.ORDER_TYPE_SELL if int(p.type) == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = float(tick.bid if int(p.type) == mt5.POSITION_TYPE_BUY else tick.ask)
            order = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(p.volume), "type": close_type,
                     "position": int(p.ticket), "price": price, "deviation": int(req.get("deviation", 20)), "magic": MAGIC,
                     "comment": str(req.get("comment", "ManiQuantAI"))[:31], "type_time": mt5.ORDER_TIME_GTC,
                     "type_filling": getattr(info, "filling_mode", mt5.ORDER_FILLING_IOC)}
            check = mt5.order_check(order)
            if check is None or getattr(check, "retcode", 0) not in (0, mt5.TRADE_RETCODE_DONE):
                raise RuntimeError(f"MT5 close order_check rejected: {getattr(check, 'retcode', None)} {getattr(check, 'comment', '')}")
            result = mt5.order_send(order)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                raise RuntimeError(f"MT5 close rejected: {getattr(result, 'retcode', None)} {getattr(result, 'comment', '')}")
        post(c, f"/api/mt5-bridge/execution/{job['id']}/complete", {"job_id": job["id"], "result": {"status": "closed", "symbol": symbol, "account": account_snapshot()}})
        return
    if side not in {"buy", "sell"}:
        raise RuntimeError(f"Unsupported execution side: {side}")
    volume = float(req["volume"])
    price = float(tick.ask if side == "buy" else tick.bid)
    order = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume,
             "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL, "price": price,
             "sl": float(req.get("stop_loss") or 0), "tp": float(req.get("take_profit") or 0),
             "deviation": int(req.get("deviation", 20)), "magic": MAGIC,
             "comment": str(req.get("comment", "ManiQuantAI"))[:31], "type_time": mt5.ORDER_TIME_GTC,
             "type_filling": getattr(info, "filling_mode", mt5.ORDER_FILLING_IOC)}
    check = mt5.order_check(order)
    if check is None:
        raise RuntimeError("MT5 order_check returned no result")
    if getattr(check, "retcode", 0) not in (0, mt5.TRADE_RETCODE_DONE):
        raise RuntimeError(f"MT5 order_check rejected: {getattr(check, 'retcode', None)} {getattr(check, 'comment', '')}")
    result = mt5.order_send(order)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"MT5 order rejected: {getattr(result, 'retcode', None)} {getattr(result, 'comment', '')}")
    time.sleep(0.15)
    confirmed = positions(symbol)
    post(c, f"/api/mt5-bridge/execution/{job['id']}/complete", {"job_id": job["id"], "result": {
        "retcode": int(result.retcode), "order": int(result.order), "deal": int(result.deal),
        "volume": float(result.volume), "price": float(result.price), "comment": str(result.comment),
        "position_count_after": len(confirmed), "account": account_snapshot()}})


def main() -> None:
    initialize_mt5()
    seen: dict[str, float] = {}
    last_scan = 0.0; last_heartbeat = 0.0; last_jobs = 0.0
    with client() as c:
        print("ManiQuantAI realtime MT5 bridge online")
        while True:
            now = time.monotonic()
            try:
                ensure_mt5()
                if now - last_heartbeat >= HEARTBEAT_SECONDS:
                    acct = account_snapshot()
                    post(c, "/api/mt5-bridge/heartbeat", {"symbol": "", "bid": 0, "ask": 0,
                        "account_login": acct.get("login", 0), "server": acct.get("server", ""),
                        "equity": acct.get("equity", 0), "balance": acct.get("balance", 0),
                        "bridge_version": "2.0-realtime", "scan_interval_ms": int(SCAN_SECONDS * 1000)})
                    last_heartbeat = now
                if now - last_scan >= SCAN_SECONDS:
                    data = get(c, "/api/mt5-bridge/live-strategies")
                    for strategy in data.get("strategies", []):
                        signal = evaluate(strategy)
                        if signal and signal["signal_key"] not in seen:
                            result = post(c, "/api/mt5-bridge/live-signal", signal)
                            print("Signal:", strategy.get("name"), result)
                            seen[signal["signal_key"]] = now
                    # Prevent unbounded memory growth while retaining recent dedupe keys.
                    seen = {k: t for k, t in seen.items() if now - t < 86400}
                    last_scan = now
                if now - last_jobs >= JOB_SECONDS:
                    jobs = get(c, "/api/mt5-bridge/jobs")
                    for job in jobs.get("jobs", []):
                        try:
                            execute(c, job) if job.get("job_type") == "execution" else None
                        except Exception as exc:
                            try: post(c, f"/api/mt5-bridge/execution/{job['id']}/fail", {"job_id": job["id"], "error": str(exc)[:1000]})
                            except Exception: pass
                    last_jobs = now
            except Exception as exc:
                print("Bridge loop warning:", exc)
                time.sleep(0.25)
            time.sleep(0.05)


if __name__ == "__main__":
    try:
        main()
    finally:
        mt5.shutdown()
