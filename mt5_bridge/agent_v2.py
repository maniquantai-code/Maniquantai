"""ManiQuantAI — MT5 Bridge Agent v2

Upgraded Windows bridge that:
  1. Polls for queued bar-data requests AND execution jobs (existing behaviour)
  2. Polls /api/mt5-bridge/live-strategies and runs the agent team locally
     for each approved strategy — fires live signals back to the cloud
  3. Monitors open positions and reports P&L every heartbeat
  4. Supports any MT5 symbol (crypto, forex, commodities, indices)

Run via bridge_app.py (Tkinter GUI) or standalone:
    MT5_BRIDGE_TOKEN=... MANIQUANT_API_URL=... python agent_v2.py
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import MetaTrader5 as mt5
import requests

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("maniquant.bridge")

# ── Timeframe map ─────────────────────────────────────────────────────────────

TF_MAP: dict[str, int] = {
    "1m":  mt5.TIMEFRAME_M1  if hasattr(mt5, "TIMEFRAME_M1")  else 1,
    "5m":  mt5.TIMEFRAME_M5  if hasattr(mt5, "TIMEFRAME_M5")  else 5,
    "15m": mt5.TIMEFRAME_M15 if hasattr(mt5, "TIMEFRAME_M15") else 15,
    "30m": mt5.TIMEFRAME_M30 if hasattr(mt5, "TIMEFRAME_M30") else 30,
    "1h":  mt5.TIMEFRAME_H1  if hasattr(mt5, "TIMEFRAME_H1")  else 60,
    "4h":  mt5.TIMEFRAME_H4  if hasattr(mt5, "TIMEFRAME_H4")  else 240,
    "1d":  mt5.TIMEFRAME_D1  if hasattr(mt5, "TIMEFRAME_D1")  else 1440,
}

def _tf(s: str) -> int:
    return TF_MAP.get(s.lower(), mt5.TIMEFRAME_M15)


# ── MT5 helpers ──────────────────────────────────────────────────────────────

def _account() -> dict:
    a = mt5.account_info()
    t = mt5.terminal_info()
    if a is None:
        return {"connected": False}
    return {
        "connected":  bool(t and t.connected),
        "login":      int(a.login),
        "server":     str(a.server),
        "currency":   str(a.currency),
        "balance":    float(a.balance),
        "equity":     float(a.equity),
        "margin":     float(a.margin),
        "margin_free": float(a.margin_free),
        "profit":     float(a.profit),
    }


def _select(symbol: str) -> None:
    sym = symbol.upper()
    if not mt5.symbol_select(sym, True):
        raise RuntimeError(f"Symbol unavailable in MT5: {sym}")


def _bars(symbol: str, tf_str: str, count: int = 300) -> list[dict]:
    _select(symbol)
    bars = mt5.copy_rates_from_pos(symbol.upper(), _tf(tf_str), 0, count)
    if bars is None or len(bars) == 0:
        raise RuntimeError(f"No bars for {symbol}/{tf_str}: {mt5.last_error()}")
    return [
        {
            "ts":          int(b["time"]) * 1000,
            "time":        int(b["time"]),
            "open":        float(b["open"]),
            "high":        float(b["high"]),
            "low":         float(b["low"]),
            "close":       float(b["close"]),
            "volume":      float(b["tick_volume"]),
            "tick_volume": int(b["tick_volume"]),
        }
        for b in bars
    ]


def _bars_range(symbol: str, tf_str: str, date_from: str, date_to: str) -> list[dict]:
    _select(symbol)
    def _dt(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    data = mt5.copy_rates_range(symbol.upper(), _tf(tf_str), _dt(date_from), _dt(date_to))
    if data is None or len(data) == 0:
        raise RuntimeError(f"MT5 rates failed: {mt5.last_error()}")
    return [
        {
            "ts":          int(b["time"]) * 1000,
            "time":        int(b["time"]),
            "open":        float(b["open"]),
            "high":        float(b["high"]),
            "low":         float(b["low"]),
            "close":       float(b["close"]),
            "volume":      float(b["tick_volume"]),
            "tick_volume": int(b["tick_volume"]),
        }
        for b in data
    ]


def _open_positions(magic: int = 260821) -> list[dict]:
    positions = mt5.positions_get()
    if not positions:
        return []
    result = []
    for p in positions:
        if p.magic != magic:
            continue
        result.append({
            "ticket":      int(p.ticket),
            "symbol":      str(p.symbol),
            "type":        "long" if p.type == mt5.POSITION_TYPE_BUY else "short",
            "volume":      float(p.volume),
            "open_price":  float(p.price_open),
            "current_price": float(p.price_current),
            "sl":          float(p.sl),
            "tp":          float(p.tp),
            "profit":      float(p.profit),
            "swap":        float(p.swap),
            "magic":       int(p.magic),
            "comment":     str(p.comment),
            "open_time":   int(p.time),
        })
    return result


def _execute_order(req: dict) -> dict:
    symbol = str(req["symbol"]).upper()
    _select(symbol)
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        raise RuntimeError(f"Cannot read live price for {symbol}")

    side = str(req["side"]).lower()
    if side not in {"buy", "sell"}:
        raise RuntimeError(f"Invalid side: {side}")

    volume = float(req["volume"])
    price  = float(tick.ask if side == "buy" else tick.bid)

    # Use broker's supported filling mode
    filling_modes = {
        1: mt5.ORDER_FILLING_FOK,
        2: mt5.ORDER_FILLING_IOC,
        4: mt5.ORDER_FILLING_RETURN,
    }
    fill_raw = getattr(info, "filling_mode", 2)
    filling = filling_modes.get(fill_raw, mt5.ORDER_FILLING_IOC)

    sl = float(req.get("stop_loss") or 0)
    tp = float(req.get("take_profit") or 0)

    order_req = {
        "action":      mt5.TRADE_ACTION_DEAL,
        "symbol":      symbol,
        "volume":      volume,
        "type":        mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
        "price":       price,
        "sl":          sl,
        "tp":          tp,
        "deviation":   int(req.get("deviation", 20)),
        "magic":       int(req.get("magic", 260821)),
        "comment":     str(req.get("reason", "ManiQuantAI"))[:31],
        "type_time":   mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    # Pre-check
    check = mt5.order_check(order_req)
    if check is not None and getattr(check, "retcode", 0) not in (0, mt5.TRADE_RETCODE_DONE):
        raise RuntimeError(f"MT5 order_check rejected: {getattr(check, 'comment', check)}")

    result = mt5.order_send(order_req)
    if result is None:
        raise RuntimeError(f"MT5 order_send returned None: {mt5.last_error()}")
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"MT5 order rejected retcode={result.retcode} comment={result.comment}")

    return {
        "retcode":  int(result.retcode),
        "order":    int(result.order),
        "deal":     int(result.deal),
        "volume":   float(result.volume),
        "price":    float(result.price),
        "comment":  str(result.comment),
        "symbol":   symbol,
        "side":     side,
        "account":  _account(),
    }


def _close_position(ticket: int, symbol: str, volume: float) -> dict:
    """Close a specific open position by ticket."""
    _select(symbol)
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        raise RuntimeError(f"Position {ticket} not found")
    pos = positions[0]
    tick = mt5.symbol_info_tick(symbol.upper())
    if tick is None:
        raise RuntimeError(f"Cannot read tick for {symbol}")

    # Close opposite side
    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask

    req = {
        "action":      mt5.TRADE_ACTION_DEAL,
        "position":    ticket,
        "symbol":      symbol.upper(),
        "volume":      volume,
        "type":        close_type,
        "price":       price,
        "deviation":   20,
        "magic":       int(pos.magic),
        "comment":     "ManiQuantAI close",
        "type_time":   mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(req)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        err = mt5.last_error()
        raise RuntimeError(f"Close failed retcode={getattr(result,'retcode','?')}: {err}")
    return {"retcode": result.retcode, "order": result.order, "price": result.price, "volume": result.volume}


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(api: str, token: str, path: str, params: dict | None = None, timeout: int = 15) -> dict:
    r = requests.get(f"{api}{path}", params={"token": token, **(params or {})}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post(api: str, token: str, path: str, payload: dict, timeout: int = 30) -> dict:
    r = requests.post(f"{api}{path}", json={"token": token, **payload}, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ── Agent team integration ────────────────────────────────────────────────────

def _load_agent_team():
    """Import agent team dynamically — graceful if not installed."""
    try:
        from maniquant_production.backend.core.agent_team import run_agent_team
        return run_agent_team
    except ImportError:
        pass
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(__file__))
        from agent_team import run_agent_team
        return run_agent_team
    except ImportError:
        return None


def _run_strategy_scan(
    api: str,
    token: str,
    strategy: dict,
    run_agent_team,
    magic: int = 260821,
) -> None:
    """Fetch live bars → run agent team → post signal if approved."""
    sid        = strategy["strategy_id"]
    symbol     = str(strategy.get("symbol") or strategy.get("live_symbol") or "BTCUSD").upper()
    tf_str     = str(strategy.get("timeframe") or strategy.get("live_timeframe") or "15m")
    spec       = strategy.get("spec") or {}
    params     = spec.get("runtime") or spec.get("parsed_strategy") or {}
    bar_count  = int(params.get("lookback_bars", 300))

    try:
        bars = _bars(symbol, tf_str, bar_count)
    except Exception as e:
        log.warning("Bars fetch failed %s/%s: %s", symbol, tf_str, e)
        return

    # Determine current position
    open_pos = _open_positions(magic)
    sym_pos  = [p for p in open_pos if p["symbol"] == symbol]
    current_position = "flat"
    if sym_pos:
        current_position = sym_pos[0]["type"]   # long | short

    result = run_agent_team(
        bars=bars,
        symbol=symbol,
        timeframe=tf_str,
        strategy_params=params,
        current_position=current_position,
        account_equity=_account().get("equity", 10000),
    )

    log.info(
        "Agent scan %s %s/%s consensus=%.3f execute=%s",
        sid[:8], symbol, tf_str, result.get("consensus", 0), result.get("execute")
    )

    if not result.get("execute"):
        return

    side = result.get("side")
    if side not in {"buy", "sell"}:
        return

    # Build signal_key from last bar timestamp
    last_ts = bars[-1].get("ts", bars[-1].get("time", 0))
    signal_key = f"{sid[:16]}-{symbol}-{side}-{last_ts}"

    try:
        _post(api, token, "/api/mt5-bridge/live-signal", {
            "strategy_id":  sid,
            "symbol":       symbol,
            "timeframe":    tf_str,
            "side":         side,
            "volume":       max(0.01, round(0.01 * result.get("volume_pct", 1.0) * 10, 2)),
            "stop_loss":    result.get("stop_loss"),
            "take_profit":  result.get("take_profit"),
            "risk_percent": result.get("risk_pct", 1.0),
            "reason":       (result.get("reason") or "")[:500],
            "signal_key":   signal_key,
            "deviation":    20,
            "magic":        magic,
        })
        log.info("Live signal queued: %s %s %s", sid[:8], side.upper(), symbol)
    except Exception as e:
        log.error("Signal post failed: %s", e)


# ── Job handlers ──────────────────────────────────────────────────────────────

def _handle_job(api: str, token: str, job: dict) -> None:
    jid  = job["id"]
    jtype = job.get("job_type", "market_data")

    if jtype == "execution":
        req = job.get("request") or {}
        result = _execute_order(req)
        _post(api, token, f"/api/mt5-bridge/execution/{jid}/complete", {"job_id": jid, "result": result})
        log.info("Executed %s %s %s @ %s", req.get("side","?").upper(), req.get("symbol","?"), req.get("volume","?"), result.get("price","?"))

    elif jtype == "close_position":
        req = job.get("request") or {}
        result = _close_position(int(req["ticket"]), str(req["symbol"]), float(req["volume"]))
        _post(api, token, f"/api/mt5-bridge/jobs/{jid}/complete", {"job_id": jid, "result": result, "rates": []})
        log.info("Closed position ticket=%s", req.get("ticket"))

    else:
        # market_data
        sym     = str(job.get("symbol", "BTCUSD")).upper()
        tf_str  = str(job.get("timeframe", "15m"))
        count   = int(job.get("count", 300))
        date_from = job.get("date_from")
        date_to   = job.get("date_to")

        if date_from and date_to:
            bar_data = _bars_range(sym, tf_str, date_from, date_to)
        else:
            bar_data = _bars(sym, tf_str, count)

        _post(api, token, f"/api/mt5-bridge/jobs/{jid}/complete", {
            "job_id": jid,
            "rates":  bar_data,
            "account": _account(),
        })
        log.debug("Delivered %d bars %s/%s job=%s", len(bar_data), sym, tf_str, jid)


# ── Main bridge loop ──────────────────────────────────────────────────────────

def run_bridge(
    api: str,
    token: str,
    poll: float = 2.0,
    agent_scan_interval: float = 30.0,
    magic: int = 260821,
    on_status=None,
):
    """
    Main bridge loop.
    - Every `poll` seconds: fetch + execute queued jobs.
    - Every `agent_scan_interval` seconds: fetch approved live strategies and
      run the agent team, posting signals when consensus fires.
    - Heartbeat is sent on every successful poll via the jobs endpoint.
    """
    api = api.rstrip("/")
    run_agent_team = _load_agent_team()
    if run_agent_team is None:
        log.warning("Agent team module not found — live strategy scanning disabled. Execution jobs still work.")
    else:
        log.info("Agent team loaded ✓")

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
    log.info("MT5 terminal connected")

    acct = _account()
    if on_status:
        on_status("Connected", acct)

    last_agent_scan = 0.0

    try:
        while True:
            now = time.time()

            # ── Job queue poll ──────────────────────────────────────────────
            try:
                data = _get(api, token, "/api/mt5-bridge/jobs")
                jobs = data.get("jobs", [])
                acct = _account()
                if on_status:
                    on_status("Online", acct)
                for job in jobs:
                    try:
                        _handle_job(api, token, job)
                    except Exception as exc:
                        log.exception("Job %s failed", job.get("id"))
                        jid   = job["id"]
                        jtype = job.get("job_type", "market_data")
                        fail_path = (
                            f"/api/mt5-bridge/execution/{jid}/fail"
                            if jtype == "execution"
                            else f"/api/mt5-bridge/jobs/{jid}/fail"
                        )
                        try:
                            _post(api, token, fail_path, {"job_id": jid, "error": str(exc)[:1000]})
                        except Exception:
                            log.exception("Could not report job failure")

            except Exception as exc:
                log.warning("Poll error: %s", exc)
                if on_status:
                    on_status(f"Offline: {exc}", None)

            # ── Agent team scan ─────────────────────────────────────────────
            if run_agent_team and (now - last_agent_scan) >= agent_scan_interval:
                try:
                    strats_data = _get(api, token, "/api/mt5-bridge/live-strategies")
                    strategies  = strats_data.get("strategies", [])
                    log.info("Agent scan: %d live strategies", len(strategies))
                    for strat in strategies:
                        try:
                            _run_strategy_scan(api, token, strat, run_agent_team, magic)
                        except Exception as e:
                            log.warning("Strategy scan error %s: %s", strat.get("strategy_id","?")[:8], e)
                    last_agent_scan = time.time()
                except Exception as exc:
                    log.warning("Live strategies fetch failed: %s", exc)

            time.sleep(poll)

    finally:
        mt5.shutdown()
        log.info("MT5 shutdown complete")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    api   = os.environ["MANIQUANT_API_URL"]
    token = os.environ["MT5_BRIDGE_TOKEN"]
    poll  = float(os.getenv("MT5_BRIDGE_POLL_SECONDS", "2"))
    scan  = float(os.getenv("MT5_BRIDGE_SCAN_INTERVAL", "30"))
    magic = int(os.getenv("MT5_BRIDGE_MAGIC", "260821"))

    run_bridge(api, token, poll=poll, agent_scan_interval=scan, magic=magic)


if __name__ == "__main__":
    main()
