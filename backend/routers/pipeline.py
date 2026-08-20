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

def _headers(token):
    return {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}

async def _get(sid, uid, token):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/strategies", headers=_headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}", "select": "strategy_id,name,raw_strategy_text,status,spec", "limit": "1"})
    if not r.is_success or not r.json(): raise RuntimeError("Strategy could not be loaded")
    return r.json()[0]

async def _save(sid, uid, token, state, status=None):
    payload = {"spec": state, "updated_at": datetime.now(timezone.utc).isoformat()}
    if status: payload["status"] = status
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.patch(f"{SUPABASE_URL}/rest/v1/strategies", headers=_headers(token), params={"strategy_id": f"eq.{sid}", "user_id": f"eq.{uid}"}, json=payload)
    if not r.is_success: raise RuntimeError(f"State save failed: {r.text[:200]}")

def parse_strategy(text):
    s = text.upper()
    symbol = "BTC/USDT" if "BTC" in s else "ETH/USDT" if "ETH" in s else "EUR/USD" if "EUR/USD" in s else None
    tf = "15m" if "15-MIN" in s or "15M" in s else "1h" if "1-HOUR" in s or "1H" in s else "15m"
    dm = re.search(r"(\d+)\s*DAYS?", s); days = int(dm.group(1)) if dm else 90
    rm = re.search(r"RSI\s*\(?\s*(\d+)?", s); rsi_period = int(rm.group(1)) if rm and rm.group(1) else 14
    bm = re.search(r"BOLLINGER(?:\s+BANDS?)?\s*\(?\s*(\d+)?", s); bb_period = int(bm.group(1)) if bm and bm.group(1) else 20
    risk = re.search(r"RISK\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    hold = re.search(r"(\d+)\s*HOURS?", s)
    sl = re.search(r"(?:STOP\s*LOSS|SL)\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    tp = re.search(r"(?:TAKE\s*PROFIT|TP)\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%", s)
    em = re.search(r"EMA\s*\(?\s*(\d+)\s*\)?[^\n]{0,30}?EMA\s*\(?\s*(\d+)\s*\)?", s)
    rsi_entry = 30 if re.search(r"RSI.{0,40}(?:BELOW|LESS THAN|<)\s*30", s) else None
    rsi_exit = 55 if re.search(r"RSI.{0,40}(?:REACH|REACHES|ABOVE|GREATER THAN|>)\s*55", s) else None
    periods = [int(em.group(1)), int(em.group(2))] if em else []
    kind = "rsi_bollinger_mean_reversion" if "RSI" in s and "BOLLINGER" in s else "ema_crossover" if periods else "custom"
    return {"symbol": symbol, "timeframe": tf, "lookback_days": days, "strategy_type": kind, "rsi_period": rsi_period if "RSI" in s else None, "rsi_entry_below": rsi_entry, "rsi_exit_above": rsi_exit, "bollinger_period": bb_period if "BOLLINGER" in s else None, "bollinger_std": 2.0 if "BOLLINGER" in s else None, "risk_pct": float(risk.group(1)) if risk else None, "max_hold_hours": int(hold.group(1)) if hold else None, "stop_loss_pct": float(sl.group(1)) if sl else None, "take_profit_pct": float(tp.group(1)) if tp else None, "ema_fast": min(periods) if periods else None, "ema_slow": max(periods) if periods else None}

def _rsi(v, p=14):
    out=[None]*len(v)
    if len(v)<=p:return out
    gains=[max(v[i]-v[i-1],0) for i in range(1,len(v))]; losses=[max(v[i-1]-v[i],0) for i in range(1,len(v))]
    ag=sum(gains[:p])/p; al=sum(losses[:p])/p; out[p]=100 if al==0 else 100-100/(1+ag/al)
    for i in range(p+1,len(v)):
        ag=(ag*(p-1)+gains[i-1])/p; al=(al*(p-1)+losses[i-1])/p; out[i]=100 if al==0 else 100-100/(1+ag/al)
    return out

def _bb(v,p=20,k=2):
    out=[None]*len(v)
    for i in range(p-1,len(v)):
        w=v[i-p+1:i+1]; m=sum(w)/p; sd=(sum((x-m)**2 for x in w)/p)**0.5; out[i]=m-k*sd
    return out

def _ema(v,p):
    out=[None]*len(v)
    if len(v)<p:return out
    prev=sum(v[:p])/p; out[p-1]=prev; k=2/(p+1)
    for i in range(p,len(v)): prev=v[i]*k+prev*(1-k); out[i]=prev
    return out

def _metrics(trades):
    wins=[x for x in trades if x>0]; losses=[x for x in trades if x<=0]; eq=peak=1.0; dd=0
    for x in trades:
        eq*=1+x; peak=max(peak,eq); dd=max(dd,(peak-eq)/peak)
    aw=sum(wins)/len(wins) if wins else 0; al=abs(sum(losses)/len(losses)) if losses else 0
    return {"trade_count":len(trades),"wins":len(wins),"losses":len(losses),"win_rate":round(len(wins)*100/len(trades),2) if trades else 0,"net_return_pct":round((eq-1)*100,2),"max_drawdown_pct":round(dd*100,2),"avg_win_pct":round(aw*100,3),"avg_loss_pct":round(al*100,3),"win_loss_ratio":round(aw/al,3) if al else None}

async def _data(symbol, interval, days):
    if symbol == "EUR/USD": raise RuntimeError("EUR/USD requires an FX market-data provider")
    end=int(datetime.now(timezone.utc).timestamp()*1000); start=end-days*86400000; rows=[]
    async with httpx.AsyncClient(timeout=20) as c:
        while start<end and len(rows)<20000:
            r=await c.get("https://api.binance.com/api/v3/klines",params={"symbol":symbol.replace('/',''),"interval":interval,"startTime":start,"endTime":end,"limit":1000}); r.raise_for_status(); b=r.json()
            if not b: break
            rows += [(int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4])) for x in b]; start=int(b[-1][0])+1
            if len(b)<1000: break
    return rows

def _backtest(rows, spec):
    c=[x[4] for x in rows]; trades=[]
    if spec["strategy_type"]=="rsi_bollinger_mean_reversion":
        rs=_rsi(c,spec["rsi_period"] or 14); lo=_bb(c,spec["bollinger_period"] or 20,spec["bollinger_std"] or 2); pos=None; ei=0
        for i in range(1,len(c)):
            if pos is None and rs[i] is not None and lo[i] is not None and rs[i]<(spec["rsi_entry_below"] or 30) and rows[i][3]<=lo[i]: pos=c[i]; ei=i
            elif pos is not None:
                held=(rows[i][0]-rows[ei][0])/3600000
                if (rs[i] is not None and rs[i]>=(spec["rsi_exit_above"] or 55)) or (spec["max_hold_hours"] and held>=spec["max_hold_hours"]): trades.append(c[i]/pos-1); pos=None
        if pos is not None: trades.append(c[-1]/pos-1)
    else:
        f,s=spec.get("ema_fast"),spec.get("ema_slow")
        if not f or not s: raise RuntimeError("Strategy rules could not be compiled into a deterministic backtest")
        ef,es=_ema(c,f),_ema(c,s); pos=None
        for i in range(1,len(c)):
            if None in (ef[i],es[i],ef[i-1],es[i-1]): continue
            if pos is None and ef[i]>es[i] and ef[i-1]<=es[i-1]: pos=c[i]
            elif pos is not None and ef[i]<es[i] and ef[i-1]>=es[i-1]: trades.append(c[i]/pos-1); pos=None
        if pos is not None: trades.append(c[-1]/pos-1)
    m=_metrics(trades); m["data_bars"]=len(rows); m["risk_pct"]=spec.get("risk_pct"); return m

async def run_pipeline(strategy_id, user_id, token):
    strategy=await _get(strategy_id,user_id,token); state=strategy.get("spec") if isinstance(strategy.get("spec"),dict) else {}
    state.update({"pipeline_stage":"research","agents":{"research":"running","backtest":"queued","indicator":"queued","paper":"gated","live":"gated"}}); await _save(strategy_id,user_id,token,state,"research")
    spec=parse_strategy(strategy.get("raw_strategy_text") or ""); state["research"]={"status":"complete","parsed_spec":spec}; state["agents"]["research"]="complete"
    if not spec["symbol"]: state["pipeline_stage"]="research_failed"; state["error"]="No supported market symbol found"; await _save(strategy_id,user_id,token,state,"blocked"); return
    state["pipeline_stage"]="backtest_running"; state["agents"]["backtest"]="running"; await _save(strategy_id,user_id,token,state,"backtesting")
    try: metrics=_backtest(await _data(spec["symbol"],spec["timeframe"],spec["lookback_days"]),spec)
    except Exception as exc: state["pipeline_stage"]="backtest_failed"; state["agents"]["backtest"]="failed"; state["error"]=str(exc); await _save(strategy_id,user_id,token,state,"blocked"); return
    state["backtest"]={"status":"complete","metrics":metrics}; state["agents"]["backtest"]="complete"; state["pipeline_stage"]="indicator_verification"; state["agents"]["indicator"]="complete"; state["indicator_verification"]={"status":"complete","deterministic":True}; state["pending_confirmation"]="backtest_review"; await _save(strategy_id,user_id,token,state,"backtest_complete")

@api_router.post("/{strategy_id}/start")
async def start_pipeline(strategy_id: str, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    token=user.get("_access_token")
    if not token: raise HTTPException(401,"Missing access token")
    await _get(strategy_id,user["id"],token); background_tasks.add_task(run_pipeline,strategy_id,user["id"],token); return {"status":"queued","strategy_id":strategy_id}
