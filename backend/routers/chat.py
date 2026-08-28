"""ManiQuantAI v2 — production-grade chat workflow.

Every error produces a helpful, user-friendly message.
No raw error codes or exception text ever reaches the user.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .auth import get_current_user
from ..core.agent_pipeline import run_post_backtest_agents
from ..core.strategy_compiler import compile_strategy
from ..core.strategy_compiler_v2 import compile_strategy_v2
from .pipeline_mt5 import run_backtest, run_research

log = logging.getLogger("maniquantai.chat")

api_router = APIRouter(prefix="/api", tags=["chat"])
SB   = "https://zuimeyynaarjsovnqilk.supabase.co"
ANON = "sb_publishable_Uf0ECWKkKrH6pzedVbTOA_aNlp1J1X"


# ─── Models ──────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    strategy_id: str
    message: str


# ─── Helpers ─────────────────────────────────────────────────────────────────

def norm(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "").strip().lower())

def _h(token: str) -> dict:
    return {"apikey": ANON, "Authorization": f"Bearer {token}",
            "Content-Type": "application/json", "Prefer": "return=representation"}

def yes(v: str) -> bool:
    t = norm(v)
    return t in {"yes","y","approve","approved","confirm","confirmed",
                 "proceed","go ahead","do it","start","run it","ok","okay","yep","sure","lets go","let's go"}

def no(v: str) -> bool:
    return norm(v) in {"no","n","cancel","decline","declined","stop","nope","nah"}

def live_request(v: str) -> bool:
    x = norm(v)
    return x in {"4","live","go live"} or any(
        k in x for k in ("start live","live trade","live trading","do live","go live","activate live","begin live"))

def set_agents(state: dict, **kw: str) -> None:
    state["agents"] = {**state.get("agents", {}), **kw}

def has_backtest(state: dict) -> bool:
    return isinstance(state.get("backtest"), dict) and bool(state.get("backtest"))

def activity(state: dict, title: str, detail: str, status: str = "complete") -> None:
    items = list(state.get("activity", []))
    items.append({"time": datetime.now(timezone.utc).isoformat(),
                  "title": title, "detail": detail, "status": status})
    state["activity"] = items[-30:]

def out(action: str, message: str, state: dict) -> JSONResponse:
    return JSONResponse({
        "ok": True, "type": "action", "action": action, "content": message,
        "pipeline_stage":       state.get("pipeline_stage"),
        "pending_confirmation": state.get("pending_confirmation"),
        "agents":               state.get("agents", {}),
        "active_agents":        state.get("active_agents", []),
        "strategy_type":        state.get("strategy_type", "multi_signal"),
        "deterministic": True,
    })

def _runtime(state: dict) -> dict:
    return state.get("runtime") or state.get("parsed_strategy") or {}


# ─── DB helpers ───────────────────────────────────────────────────────────────

async def _load(sid: str, uid: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.get(f"{SB}/rest/v1/strategies", headers=_h(token),
                        params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}",
                                "select": "strategy_id,name,raw_strategy_text,status,spec",
                                "limit": "1"})
    if r.status_code in (401, 403):
        raise HTTPException(401, "session_expired")
    if not r.is_success:
        raise HTTPException(502, "db_unavailable")
    rows = r.json()
    if not rows:
        raise HTTPException(404, "strategy_not_found")
    return rows[0]

async def _save(sid: str, uid: str, token: str, state: dict, status: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.patch(f"{SB}/rest/v1/strategies", headers=_h(token),
                              params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"},
                              json={"spec": state, "status": status,
                                    "updated_at": datetime.now(timezone.utc).isoformat()})
        if r.status_code in (401, 403):
            raise HTTPException(401, "session_expired")
        if not r.is_success:
            log.error("Save failed %s %s", r.status_code, r.text[:200])
    except HTTPException:
        raise
    except Exception as e:
        log.error("Save exception: %s", e)
        # Don't crash the user — state is in memory, log and continue


# ─── Compiler ─────────────────────────────────────────────────────────────────

async def _compile(raw: str) -> dict:
    det = compile_strategy_v2(raw)
    if not det.get("unresolved"):
        return det
    try:
        return await compile_strategy(raw)
    except Exception:
        return det


def _compile_summary(spec: dict) -> str:
    rt    = spec.get("runtime", {})
    sym   = spec.get("symbol", "?")
    tf    = spec.get("timeframe", "?")
    stype = spec.get("strategy_type", "multi_signal").replace("_", " ")
    rp    = rt.get("risk_pct", 1)
    sl    = rt.get("stop_loss") or {}
    sl_str = f"ATR({sl.get('period',14)}) × {sl.get('multiplier',1.5)}" if sl.get("type") == "ATR" else f"{sl.get('value','?')}% stop"
    tp    = rt.get("take_profit") or {}
    tp_str = f"{tp.get('multiple',2)}R" if tp.get("type") in {"R_MULTIPLE","R-MULTIPLE"} else f"{tp.get('value','?')}%"
    agents = spec.get("active_agents", [])
    lines = [
        f"✅ **Strategy compiled — {stype} on {sym} {tf}**\n",
        f"**Entry:** RSI({rt.get('rsi_period',14)}) < {rt.get('rsi_entry_below',30)} · lower Bollinger Band({rt.get('bollinger_period',20)})" if "rsi" in stype or stype == "multi signal" else f"**Entry:** {stype} signal",
        f"**Exit:** RSI > {rt.get('rsi_exit_above',55)}",
        f"**Risk:** {rp}% per trade · Stop: {sl_str} · Target: {tp_str}",
        f"**Agent team:** {', '.join(agents)}\n",
        "The **Research Agent** is now running — I'll update you when the backtest is ready.",
    ]
    return "\n".join(lines)


# ─── Main endpoint ────────────────────────────────────────────────────────────

@api_router.post("/chat")
async def chat(req: ChatRequest, background_tasks: BackgroundTasks,
               user=Depends(get_current_user)):

    # Friendly wrappers for auth/session errors
    token = user.get("_access_token") or user.get("access_token")
    if not token:
        return JSONResponse({"ok": False, "type": "error",
                             "content": "Your session has expired. Please refresh the page and log in again.",
                             "action": "session_expired"})

    try:
        strategy = await _load(req.strategy_id, user["id"], token)
    except HTTPException as e:
        if e.status_code == 401:
            return JSONResponse({"ok": False, "type": "error",
                                 "content": "Your session expired. Please refresh the page.",
                                 "action": "session_expired"})
        if e.status_code == 404:
            return JSONResponse({"ok": False, "type": "error",
                                 "content": "This strategy no longer exists. Create a new one with **+ New**.",
                                 "action": "strategy_not_found"})
        return JSONResponse({"ok": False, "type": "error",
                             "content": "Having trouble connecting to the server. Please try again in a moment.",
                             "action": "server_error"})

    state   = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
    text    = norm(req.message)
    stage   = state.get("pipeline_stage") or ""
    pending = state.get("pending_confirmation")

    try:

        # ── 1. New strategy with no spec — compile + auto-start research ──
        if not stage or stage in ("unknown", "draft", "created", ""):
            raw = str(strategy.get("raw_strategy_text") or "").strip()
            if not raw:
                return out("needs_input",
                    "Tell me what you want to trade and I'll build the strategy for you.\n\n"
                    "**Example:**\n"
                    "> BTC/USD 15m, RSI 14 below 30 + lower Bollinger Band, exit RSI above 55, 1% risk, ATR 1.5x stop\n\n"
                    "Include your **symbol**, **timeframe**, **entry signal**, **exit signal**, and **risk %**.", state)

            spec = await _compile(raw)
            state.update(spec)
            state.update({
                "pipeline_stage":       "research_running",
                "pending_confirmation": None,
                "active_agents":        spec.get("active_agents", ["momentum","mean_reversion","breakout","sentiment"]),
                "strategy_type":        spec.get("strategy_type", "multi_signal"),
                "agents": {"research":"running","backtest":"gated","indicator":"gated","risk":"gated","live":"gated"},
            })
            activity(state, "Strategy compiled", f"{spec.get('symbol','?')} {spec.get('timeframe','?')} · {spec.get('strategy_type','?')}")
            await _save(req.strategy_id, user["id"], token, state, "research_running")
            background_tasks.add_task(_safe_research, req.strategy_id, user["id"], token)
            return out("research_started", _compile_summary(spec), state)

        # ── 2. Failed compilation — auto-recover ──────────────────────────
        if (strategy.get("status") == "strategy_compilation_failed"
                or state.get("compilation", {}).get("status") == "failed"):
            raw = str(strategy.get("raw_strategy_text") or "").strip()
            if not raw:
                return out("needs_input", "Please describe your strategy and I'll compile it.", state)
            try:
                spec = await _compile(raw)
                state.update(spec)
                state.update({
                    "pipeline_stage": "research_running",
                    "pending_confirmation": None,
                    "active_agents": spec.get("active_agents", []),
                    "strategy_type": spec.get("strategy_type", "multi_signal"),
                    "agents": {"research":"running","backtest":"gated","indicator":"gated","risk":"gated","live":"gated"},
                    "compilation": {"status": "complete", "recovered": True},
                })
                activity(state, "Strategy recovered", "Compilation succeeded on retry.")
                await _save(req.strategy_id, user["id"], token, state, "research_running")
                background_tasks.add_task(_safe_research, req.strategy_id, user["id"], token)
                return out("research_started", _compile_summary(spec), state)
            except Exception:
                return out("compilation_failed",
                    "I wasn't able to compile this strategy. Try rephrasing it more clearly:\n\n"
                    "> BTC/USD 15m · RSI 14 below 30 · Bollinger lower band · exit RSI 55 · 1% risk · ATR 1.5x stop · 2R target",
                    state)

        # ── 3. Research running — acknowledge ─────────────────────────────
        if stage == "research_running":
            return out("research_running",
                "⏳ **The Research Agent is still running.** It's pulling historical bars and verifying indicator conditions.\n\n"
                "This usually takes 20–40 seconds. I'll update you automatically when it's done.", state)

        # ── 4. Research complete — confirm backtest ───────────────────────
        if stage in ("research_complete", "awaiting_research_confirmation") or pending == "backtest":
            if yes(text):
                state.update({"pending_confirmation": None, "pipeline_stage": "backtest_running"})
                set_agents(state, research="complete", backtest="running", indicator="gated", risk="gated", live="gated")
                await _save(req.strategy_id, user["id"], token, state, "backtesting")
                background_tasks.add_task(_safe_backtest, req.strategy_id, user["id"], token)
                sym = _runtime(state).get("symbol", "?")
                return out("backtest",
                    f"📊 **Deterministic backtest running on {sym}.**\n\n"
                    "Testing every historical entry and exit signal against real price data. "
                    "No simulated or estimated results — only what the strategy actually did. "
                    "Results in ~30 seconds.", state)
            if no(text):
                return out("backtest_declined",
                    "No problem — the backtest is paused. Type **'yes'** when you're ready to run it.", state)
            # First time seeing this stage — prompt
            research = state.get("research", {})
            bars     = research.get("bars_checked", "?")
            entries  = research.get("entry_candidates", "?")
            sym      = _runtime(state).get("symbol", "?")
            src      = state.get("data_source", "market data")
            return out("backtest_ready",
                f"✅ **Research complete on {sym}**\n\n"
                f"- **{bars:,} bars** analysed from {src}\n"
                f"- **{entries} historical entry candidates** found\n\n"
                "Ready to run the **deterministic backtest** — this tests every signal against real historical prices.\n\n"
                "**Run backtest?** (yes / no)", state)

        # ── 5. Backtest running — acknowledge ─────────────────────────────
        if stage == "backtest_running":
            return out("backtest_running",
                "📊 **Backtest is running.** Testing every historical signal against real price data.\n\n"
                "Usually takes 20–30 seconds. Results coming up shortly.", state)

        # ── 6. Backtest complete → trigger indicator + risk agents ─────────
        if has_backtest(state) and state.get("agents", {}).get("indicator") in {None, "gated"}:
            if yes(text) or pending == "indicator_approval":
                result = run_post_backtest_agents(state)
                state["agents"] = {**state.get("agents", {}),
                                   "indicator": result["indicator"]["status"],
                                   "risk":      result["risk"]["status"]}
                if result["ready_for_live_gate"]:
                    state.update({"pipeline_stage": "risk_ready", "pending_confirmation": None})
                    activity(state, "Indicator + Risk Agents passed", "All checks cleared.")
                    await _save(req.strategy_id, user["id"], token, state, "risk_ready")
                    bt = state.get("backtest", {}).get("metrics", {})
                    return out("risk_ready",
                        f"✅ **All pipeline checks passed.**\n\n"
                        f"**Backtest results:** {bt.get('trade_count','?')} trades · "
                        f"{bt.get('win_rate','?')}% win rate · "
                        f"{bt.get('total_return_pct','?')}% return · "
                        f"{bt.get('max_drawdown_pct','?')}% max drawdown\n\n"
                        "Your strategy is ready for **live trading**.\n\n"
                        "Type **'start live trading'** to activate the agent team, or review the results first.", state)
                errs = "; ".join(result["indicator"]["errors"] + result["risk"]["errors"])
                activity(state, "Validation issue", errs[:240], "blocked")
                state.update({"pipeline_stage": "indicator_failed", "pending_confirmation": None})
                await _save(req.strategy_id, user["id"], token, state, "indicator_failed")
                return out("indicator_failed",
                    f"⚠️ **The strategy has a configuration issue:**\n\n{errs}\n\n"
                    "Create a new strategy with corrected parameters to fix this.", state)

            # Prompt user
            state.update({"pending_confirmation": "indicator_approval", "pipeline_stage": "indicator_ready"})
            set_agents(state, backtest="complete", indicator="gated", risk="gated", live="gated")
            await _save(req.strategy_id, user["id"], token, state, "indicator_ready")
            bt = state.get("backtest", {}).get("metrics", {})
            return out("indicator_approval",
                f"✅ **Backtest complete!**\n\n"
                f"**{bt.get('trade_count','?')} trades** · **{bt.get('win_rate','?')}% win rate** · "
                f"**{bt.get('total_return_pct','?')}% total return** · "
                f"**{bt.get('max_drawdown_pct','?')}% max drawdown**\n\n"
                "Running **Indicator Agent** and **Risk Management Agent** to validate the strategy before live approval.\n\n"
                "**Proceed?** (yes / no)", state)

        # ── 7. Risk ready — prompt for live ───────────────────────────────
        if stage == "risk_ready" or (has_backtest(state) and state.get("agents", {}).get("risk") == "complete"):
            if live_request(text) or yes(text):
                state.update({"pending_confirmation": "live_approval", "pipeline_stage": "awaiting_live_approval"})
                await _save(req.strategy_id, user["id"], token, state, "awaiting_live_approval")
                return out("live_approval",
                    "🔴 **Live trading confirmation**\n\n"
                    "The agent team will monitor the market and submit orders through **MetaTrader 5** "
                    "when the Portfolio Manager's consensus signal fires.\n\n"
                    "**Hard limits active:** 2% max risk per trade · daily loss limit · heartbeat gate\n\n"
                    "**Do you approve live trading?** (yes / no)", state)
            return out("risk_ready",
                "✅ **Strategy cleared all checks.** Type **'start live trading'** to activate the agent team.", state)

        # ── 8. Awaiting live approval ─────────────────────────────────────
        if pending == "live_approval":
            if yes(text):
                if not has_backtest(state):
                    return out("live_gated", "The backtest must complete before live trading can start.", state)
                ag = state.get("agents", {})
                if ag.get("indicator") != "complete" or ag.get("risk") != "complete":
                    return out("live_gated",
                        "The Indicator and Risk agents must pass before live trading. Type **'yes'** to run them.", state)
                state.update({"live_approved": True, "pending_confirmation": None, "pipeline_stage": "live_running"})
                set_agents(state, indicator="complete", risk="complete", live="current")
                activity(state, "Live trading approved", "Agent team active.", "running")
                await _save(req.strategy_id, user["id"], token, state, "live_approved")
                sym    = _runtime(state).get("symbol", "?")
                tf     = _runtime(state).get("timeframe", "?")
                agents = state.get("active_agents", [])
                return out("live_running",
                    f"🟢 **Live trading is now active on {sym} {tf}.**\n\n"
                    f"**Agent team:** {', '.join(agents)}\n\n"
                    "The **Portfolio Manager** aggregates all signals and only fires an order when "
                    "weighted consensus ≥ 0.35 and ≥ 2 agents agree.\n\n"
                    "Open MetaTrader 5 and start the bridge app to receive live orders. "
                    "Monitor signals in the **Agent Trading Desk** panel below.", state)
            if no(text):
                state.update({"live_approved": False, "pending_confirmation": None, "pipeline_stage": "live_blocked"})
                activity(state, "Live trading declined", "No order submitted.", "blocked")
                await _save(req.strategy_id, user["id"], token, state, "live_blocked")
                return out("live_declined",
                    "Live trading stayed off. No orders submitted. "
                    "Type **'start live trading'** whenever you're ready.", state)
            return out("live_approval",
                "**Approve live trading?** Type **yes** to activate or **no** to stay off.", state)

        # ── 9. Live shortcut from any stage ───────────────────────────────
        if live_request(text):
            if not has_backtest(state):
                return out("live_gated",
                    "The backtest hasn't run yet. Complete the research and backtest first, then activate live trading.", state)
            ag = state.get("agents", {})
            if ag.get("indicator") != "complete" or ag.get("risk") != "complete":
                state.update({"pending_confirmation": "indicator_approval"})
                await _save(req.strategy_id, user["id"], token, state, strategy.get("status","backtesting"))
                result = run_post_backtest_agents(state)
                state["agents"] = {**ag, "indicator": result["indicator"]["status"], "risk": result["risk"]["status"]}
                if result["ready_for_live_gate"]:
                    state.update({"pending_confirmation": "live_approval", "pipeline_stage": "awaiting_live_approval"})
                    await _save(req.strategy_id, user["id"], token, state, "awaiting_live_approval")
                    return out("live_approval",
                        "✅ **Indicator and Risk checks passed.** "
                        "**Approve live trading?** (yes / no)", state)
                errs = "; ".join(result["indicator"]["errors"] + result["risk"]["errors"])
                return out("indicator_failed",
                    f"⚠️ **Strategy has issues that must be fixed before live trading:**\n\n{errs}", state)
            state.update({"pending_confirmation": "live_approval", "pipeline_stage": "awaiting_live_approval"})
            await _save(req.strategy_id, user["id"], token, state, "awaiting_live_approval")
            return out("live_approval",
                "🔴 **Ready for live trading.**\n\n**Approve?** (yes / no)", state)

        # ── 10. Already live ──────────────────────────────────────────────
        if stage in ("live_running", "live_approved") or state.get("live_approved"):
            sym = _runtime(state).get("symbol", "?")
            return out("live_status",
                f"🟢 **Agent team is live on {sym}.** "
                "Monitor signals in the Agent Trading Desk panel below. "
                "Make sure your MT5 bridge is connected.", state)

        # ── 11. Research failed — offer retry ─────────────────────────────
        if stage == "research_failed":
            if yes(text):
                state.update({"pipeline_stage": "research_running", "pending_confirmation": None})
                set_agents(state, research="running")
                await _save(req.strategy_id, user["id"], token, state, "research_running")
                background_tasks.add_task(_safe_research, req.strategy_id, user["id"], token)
                return out("research_started",
                    "🔄 **Retrying the Research Agent.**\n\n"
                    "Make sure MetaTrader 5 is open and the bridge is connected for best results.", state)
            return out("research_failed",
                "⚠️ **Research couldn't complete** — usually because MetaTrader 5 isn't connected.\n\n"
                "1. Open MetaTrader 5\n"
                "2. Start the MT5 Bridge app\n"
                "3. Type **'yes'** to retry\n\n"
                "*(The system will use Yahoo Finance as a fallback if MT5 isn't available)*", state)

        # ── 12. Backtest failed — offer retry ─────────────────────────────
        if stage == "backtest_failed":
            if yes(text):
                state.update({"pipeline_stage": "backtest_running", "pending_confirmation": None})
                set_agents(state, backtest="running")
                await _save(req.strategy_id, user["id"], token, state, "backtesting")
                background_tasks.add_task(_safe_backtest, req.strategy_id, user["id"], token)
                return out("backtest", "🔄 **Retrying the backtest.**", state)
            return out("backtest_failed",
                "⚠️ **The backtest couldn't complete.**\n\n"
                "Type **'yes'** to retry. Make sure MetaTrader 5 is open for live data.", state)

        # ── 13. Catch-all — guide the user ────────────────────────────────
        stage_labels = {
            "research_complete":  "Research done — type **'yes'** to run the backtest.",
            "indicator_ready":    "Backtest done — type **'yes'** to run indicator checks.",
            "indicator_failed":   "Strategy has configuration issues. Create a new strategy with fixes.",
            "live_blocked":       "Live trading is off. Type **'start live trading'** to activate.",
            "awaiting_mt5":       "Connect MetaTrader 5 first, then type **'yes'** to retry.",
        }
        hint = stage_labels.get(stage, "Type **'yes'** to continue or **'start live trading'** to go live.")
        return out("status", hint, state)

    except HTTPException:
        raise
    except Exception as e:
        log.exception("Chat workflow error sid=%s", req.strategy_id)
        # Never show raw errors to users
        return JSONResponse({
            "ok": True, "type": "action", "action": "error",
            "content": (
                "Something went wrong on my end — no trading action was taken. "
                "Please try again in a moment. If this keeps happening, refresh the page."
            ),
            "pipeline_stage": state.get("pipeline_stage") if "state" in dir() else None,
            "deterministic": True,
        })


# ─── Safe background task wrappers ───────────────────────────────────────────

async def _safe_research(sid: str, uid: str, token: str) -> None:
    try:
        await run_research(sid, uid, token)
    except Exception as e:
        log.error("Background research failed sid=%s: %s", sid, e)

async def _safe_backtest(sid: str, uid: str, token: str) -> None:
    try:
        await run_backtest(sid, uid, token)
    except Exception as e:
        log.error("Background backtest failed sid=%s: %s", sid, e)
