"""Continuous deterministic MT5 execution bridge.

The bridge never asks an LLM for a trading decision. It downloads only
server-authorized compiled Strategy Specs, evaluates them locally against the
latest completed candle, and submits approved execution jobs to MT5.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
import MetaTrader5 as mt5

from execution_plan import build_execution_plan, evaluate_plan

API = os.environ["MANIQUANT_API"].rstrip("/")
TOKEN = os.environ["MT5_BRIDGE_TOKEN"]
SCAN_SECONDS = max(0.2, float(os.getenv("MT5_BRIDGE_SCAN_SECONDS", "0.5")))
HEARTBEAT_SECONDS = max(1.0, float(os.getenv("MT5_BRIDGE_HEARTBEAT_SECONDS", "2")))
JOB_SECONDS = max(0.2, float(os.getenv("MT5_BRIDGE_JOB_SECONDS", "0.5")))
HTTP_TIMEOUT = max(2.0, float(os.getenv("MT5_BRIDGE_HTTP_TIMEOUT", "10")))
MAGIC = int(os.getenv("MT5_BRIDGE_MAGIC", "260821"))
DEVIATION = int(os.getenv("MT5_BRIDGE_DEVIATION", "20"))
MAX_TICK_AGE = max(0.5, float(os.getenv("MT5_BRIDGE_MAX_TICK_AGE_SECONDS", "10")))
MAX_SPREAD_POINTS = max(0.0, float(os.getenv("MT5_MAX_SPREAD_POINTS", "0")))
TIMEFRAMES = {"1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30, "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1, "1w": mt5.TIMEFRAME_W1}


def client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(HTTP_TIMEOUT, connect=5), limits=httpx.Limits(max_connections=20, max_keepalive_connections=10), headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "ManiQuantAI-MT5-Bridge/3.1"})


def initialize_mt5() -> None:
    login, password, server = os.getenv("MT5_LOGIN"), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER")
    kwargs: dict[str, Any] = {"login": int(login), "password": password, "server": server} if login and password and server else {}
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")


def ensure_mt5() -> None:
    if mt5.terminal_info() is None or mt5.account_info() is None:
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
    return {"login": int(info.login), "server": str(info.server), "currency": str(info.currency), "balance": float(info.balance), "equity": float(info.equity), "margin_free": float(info.margin_free), "trade_allowed": bool(info.trade_allowed)}


def post(c: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    # The execution completion/failure endpoints require the bridge token in
    # the request body; the shared Authorization header alone is not enough.
    if path.startswith("/api/mt5-bridge/execution/") and (path.endswith("/complete") or path.endswith("/fail")):
        body.setdefault("token", TOKEN)
    r = c.post(f"{API}{path}", json=body)
    r.raise_for_status()
    return r.json()


def get(c: httpx.Client, path: str, **params: Any) -> dict[str, Any]:
    query = dict(params)
    # The current /jobs contract authenticates with the token query parameter.
    if path == "/api/mt5-bridge/jobs":
        query.setdefault("token", TOKEN)
    r = c.get(f"{API}{path}", params=query)
    r.raise_for_status()
    return r.json()


def positions(symbol: str):
    return list(mt5.positions_get(symbol=symbol) or [])


def _risk_volume(symbol: str, stop_distance: float, risk_pct: float) -> float:
    info, acct = mt5.symbol_info(symbol), mt5.account_info()
    if info is None or acct is None or stop_distance <= 0:
        return 0.0
    tick_size = float(getattr(info, "trade_tick_size", 0) or getattr(info, "point", 0) or 0)
    tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
    if tick_size <= 0 or tick_value <= 0:
        return 0.0
    loss_per_lot = stop_distance / tick_size * tick_value
    if loss_per_lot <= 0:
        return 0.0
    raw = float(acct.equity) * min(max(risk_pct, 0.0), 2.0) / 100.0 / loss_per_lot
    vmin = float(info.volume_min)
    vmax = float(info.volume_max)
    step = float(info.volume_step or info.volume_min or 0.01)
    if raw < vmin or step <= 0:
        return 0.0
    sized = (raw // step) * step
    return min(vmax, max(vmin, sized))


def _bars(symbol: str, timeframe: str):
    if timeframe not in TIMEFRAMES or not mt5.symbol_select(symbol, True):
        return None
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[timeframe], 0, 300)
    if rates is None or len(rates) < 60:
        return None
    # Exclude the currently forming candle. Every decision is based on a
    # completed candle so a signal cannot flip while a candle is forming.
    return [{"time": int(x["time"]), "open": float(x["open"]), "high": float(x["high"]), "low": float(x["low"]), "close": float(x["close"]), "tick_volume": int(x["tick_volume"])} for x in rates[:-1]]


def evaluate(strategy: dict[str, Any]) -> dict[str, Any] | None:
    spec = strategy.get("spec") or {}
    parsed = spec.get("parsed_strategy") or spec
    try:
        plan = build_execution_plan({**spec, "strategy_id": strategy.get("strategy_id") or spec.get("strategy_id")})
    except (TypeError, ValueError, KeyError):
        return None
    symbol = plan["symbol"]
    if not symbol:
        return None
    bars = _bars(symbol, plan["timeframe"])
    if not bars:
        return None
    idx = len(bars) - 1
    ps = positions(symbol)
    has_long = any(int(p.type) == mt5.POSITION_TYPE_BUY for p in ps)
    has_short = any(int(p.type) == mt5.POSITION_TYPE_SELL for p in ps)
    signal = evaluate_plan(plan, bars, idx, has_long, has_short)
    if signal is None:
        return None

    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        return None
    tick_age = time.time() - float(getattr(tick, "time", time.time()))
    if tick_age > MAX_TICK_AGE:
        return None
    spread_points = (float(tick.ask) - float(tick.bid)) / float(info.point or 1)
    if MAX_SPREAD_POINTS and spread_points > MAX_SPREAD_POINTS:
        return None

    if signal.side.startswith("close_"):
        ptype = mt5.POSITION_TYPE_BUY if signal.side == "close_buy" else mt5.POSITION_TYPE_SELL
        p = next((p for p in ps if int(p.type) == ptype), None)
        if p is None:
            return None
        return {"strategy_id": strategy["strategy_id"], "symbol": symbol, "timeframe": plan["timeframe"], "side": signal.side, "volume": float(p.volume), "risk_percent": 0.0, "reason": signal.reason, "signal_key": signal.signal_key, "candle_time": signal.candle_time, "tick_age_seconds": tick_age, "spread_points": spread_points}

    runtime = parsed.get("runtime") or {}
    risk = parsed.get("risk") or {}
    risk_pct = min(max(float(risk.get("risk_pct_per_trade", runtime.get("risk_pct", 1.0))), 0.0), 2.0)
    entry = float(tick.ask if signal.side == "buy" else tick.bid)
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    sl_cfg = runtime.get("stop_loss") or {"type": "ATR", "period": 14, "multiplier": 1.5}
    if isinstance(sl_cfg, dict) and sl_cfg.get("type") == "ATR":
        period = max(1, int(sl_cfg.get("period", 14)))
        mult = max(0.0, float(sl_cfg.get("multiplier", 1.5)))
        if len(closes) <= period:
            return None
        trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, len(closes))]
        stop_distance = sum(trs[-period:]) / period * mult
    elif isinstance(sl_cfg, dict) and sl_cfg.get("type") == "PERCENT":
        stop_distance = entry * max(0.0, float(sl_cfg.get("value", 0))) / 100.0
    else:
        return None
    if stop_distance <= 0:
        return None

    live_cfg = parsed.get("live_config") or spec.get("live_config") or {}
    volume = float(runtime.get("volume") or live_cfg.get("volume") or 0)
    if volume <= 0:
        volume = _risk_volume(symbol, stop_distance, risk_pct)
    if volume <= 0:
        return None

    sl = entry - stop_distance if signal.side == "buy" else entry + stop_distance
    tp_cfg = runtime.get("take_profit") or {"type": "R_MULTIPLE", "multiple": 2.0}
    if isinstance(tp_cfg, dict) and tp_cfg.get("type") == "R_MULTIPLE":
        tp_distance = stop_distance * max(0.0, float(tp_cfg.get("multiple", 2.0)))
    elif isinstance(tp_cfg, dict) and tp_cfg.get("type") == "PERCENT":
        tp_distance = entry * max(0.0, float(tp_cfg.get("value", 0))) / 100.0
    else:
        return None
    tp = entry + tp_distance if signal.side == "buy" else entry - tp_distance
    return {"strategy_id": strategy["strategy_id"], "symbol": symbol, "timeframe": plan["timeframe"], "side": signal.side, "volume": volume, "stop_loss": sl, "take_profit": tp, "risk_percent": risk_pct, "reason": signal.reason, "signal_key": signal.signal_key, "candle_time": signal.candle_time, "tick_age_seconds": tick_age, "spread_points": spread_points}


def _filling(info):
    mode = getattr(info, "filling_mode", None)
    return int(mode) if mode in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN) else mt5.ORDER_FILLING_IOC


def _send_checked(order: dict[str, Any]):
    check = mt5.order_check(order)
    if check is None:
        raise RuntimeError(f"MT5 order_check failed: {mt5.last_error()}")
    if getattr(check, "retcode", 0) not in (0, mt5.TRADE_RETCODE_DONE):
        raise RuntimeError(f"MT5 order_check rejected: {getattr(check, 'retcode', None)} {getattr(check, 'comment', '')}")
    result = mt5.order_send(order)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"MT5 order rejected: {getattr(result, 'retcode', None)} {getattr(result, 'comment', '')}")
    return result


def execute(c: httpx.Client, job: dict[str, Any]) -> None:
    req = job.get("request") or {}
    symbol = str(req.get("symbol", "")).upper()
    side = str(req.get("side", "")).lower()
    if not symbol or side not in {"buy", "sell", "close", "close_buy", "close_sell"}:
        raise RuntimeError("Invalid execution request")
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"MT5 symbol unavailable: {symbol}")
    tick, info = mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol)
    if tick is None or info is None:
        raise RuntimeError(f"No live tick for {symbol}")
    tick_age = time.time() - float(getattr(tick, "time", time.time()))
    if tick_age > MAX_TICK_AGE:
        raise RuntimeError(f"Stale tick: {tick_age:.2f}s")
    spread_points = (float(tick.ask) - float(tick.bid)) / float(info.point or 1)
    limit = float(req.get("max_spread_points", MAX_SPREAD_POINTS))
    if limit and spread_points > limit:
        raise RuntimeError(f"Spread {spread_points:.1f} points exceeds limit {limit:.1f}")

    if side in {"close", "close_buy", "close_sell"}:
        ps = positions(symbol)
        targets = ps if side == "close" else [p for p in ps if (side == "close_buy" and int(p.type) == mt5.POSITION_TYPE_BUY) or (side == "close_sell" and int(p.type) == mt5.POSITION_TYPE_SELL)]
        if not targets:
            post(c, f"/api/mt5-bridge/execution/{job['id']}/complete", {"job_id": job["id"], "result": {"status": "already_closed", "symbol": symbol}})
            return
        for p in targets:
            close_type = mt5.ORDER_TYPE_SELL if int(p.type) == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = float(tick.bid if int(p.type) == mt5.POSITION_TYPE_BUY else tick.ask)
            order = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(p.volume), "type": close_type, "position": int(p.ticket), "price": price, "deviation": int(req.get("deviation", DEVIATION)), "magic": MAGIC, "comment": str(req.get("comment", "ManiQuantAI"))[:31], "type_time": mt5.ORDER_TIME_GTC, "type_filling": _filling(info)}
            _send_checked(order)
        post(c, f"/api/mt5-bridge/execution/{job['id']}/complete", {"job_id": job["id"], "result": {"status": "closed", "symbol": symbol, "account": account_snapshot()}})
        return

    volume = float(req.get("volume", 0))
    if volume <= 0:
        raise RuntimeError("Execution volume must be positive")
    price = float(tick.ask if side == "buy" else tick.bid)
    order = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume, "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL, "price": price, "sl": float(req.get("stop_loss") or 0), "tp": float(req.get("take_profit") or 0), "deviation": int(req.get("deviation", DEVIATION)), "magic": MAGIC, "comment": str(req.get("comment", "ManiQuantAI"))[:31], "type_time": mt5.ORDER_TIME_GTC, "type_filling": _filling(info)}
    result = _send_checked(order)
    time.sleep(0.15)
    confirmed = positions(symbol)
    post(c, f"/api/mt5-bridge/execution/{job['id']}/complete", {"job_id": job["id"], "result": {"retcode": int(result.retcode), "order": int(result.order), "deal": int(result.deal), "volume": float(result.volume), "price": float(result.price), "comment": str(result.comment), "position_count_after": len(confirmed), "account": account_snapshot()}})


def main() -> None:
    initialize_mt5()
    seen: dict[str, float] = {}
    last_scan = last_heartbeat = last_jobs = 0.0
    with client() as c:
        print("ManiQuantAI deterministic MT5 bridge online")
        while True:
            now = time.monotonic()
            try:
                ensure_mt5()
                if now - last_heartbeat >= HEARTBEAT_SECONDS:
                    acct = account_snapshot()
                    post(c, "/api/mt5-bridge/heartbeat", {"symbol": "", "bid": 0, "ask": 0, "account_login": acct.get("login", 0), "server": acct.get("server", ""), "equity": acct.get("equity", 0), "balance": acct.get("balance", 0), "bridge_version": "3.1-deterministic", "scan_interval_ms": int(SCAN_SECONDS * 1000)})
                    last_heartbeat = now
                if now - last_scan >= SCAN_SECONDS:
                    data = get(c, "/api/mt5-bridge/live-strategies")
                    for strategy in data.get("strategies", []):
                        signal = evaluate(strategy)
                        if signal and signal["signal_key"] not in seen:
                            result = post(c, "/api/mt5-bridge/live-signal", signal)
                            print("Signal:", strategy.get("name"), result)
                            seen[signal["signal_key"]] = now
                    seen = {k: t for k, t in seen.items() if now - t < 86400}
                    last_scan = now
                if now - last_jobs >= JOB_SECONDS:
                    jobs = get(c, "/api/mt5-bridge/jobs")
                    for job in jobs.get("jobs", []):
                        if job.get("job_type") != "execution":
                            continue
                        try:
                            execute(c, job)
                        except Exception as exc:
                            try:
                                post(c, f"/api/mt5-bridge/execution/{job['id']}/fail", {"job_id": job["id"], "error": str(exc)[:1000]})
                            except Exception:
                                pass
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
