"""Deterministic strategy pipeline backed by the user's MT5 terminal bridge."""
from __future__ import annotations
import asyncio, math, os, re
from datetime import datetime, timezone, timedelta
from typing import Any
import httpx
from fastapi import APIRouter, Depends, HTTPException
from .auth import get_current_user

api_router=APIRouter(prefix="/api/pipeline",tags=["pipeline"])
SB=os.getenv("SUPABASE_URL","https://zuimeyynaarjsovnqilk.supabase.co"); ANON=os.getenv("SUPABASE_ANON_KEY",""); SERVICE=os.getenv("SUPABASE_SERVICE_ROLE_KEY","")
def h(t): return {"apikey":ANON,"Authorization":f"Bearer {t}","Content-Type":"application/json","Prefer":"return=representation"}
def sh(): return {"apikey":SERVICE,"Authorization":f"Bearer {SERVICE}","Content-Type":"application/json","Prefer":"return=representation"}
async def load(sid,uid,t):
 async with httpx.AsyncClient(timeout=15) as c:r=await c.get(f"{SB}/rest/v1/strategies",headers=h(t),params={"strategy_id":f"eq.{sid}","user_id":f"eq.{uid}","select":"strategy_id,name,raw_strategy_text,status,spec","limit":"1"})
 if not r.is_success or not r.json(): raise RuntimeError("Strategy could not be loaded")
 return r.json()[0]
async def save(sid,uid,t,state,status=None):
 p={"spec":state,"updated_at":datetime.now(timezone.utc).isoformat()}; p.update({"status":status} if status else {})
 async with httpx.AsyncClient(timeout=15) as c:r=await c.patch(f"{SB}/rest/v1/strategies",headers=h(t),params={"strategy_id":f"eq.{sid}","user_id":f"eq.{uid}"},json=p)
 if not r.is_success: raise RuntimeError("Strategy state could not be saved")
async def connected(uid,t):
 async with httpx.AsyncClient(timeout=10) as c:r=await c.get(f"{SB}/rest/v1/broker_accounts",headers=h(t),params={"user_id":f"eq.{uid}","connector_type":"eq.mt5","select":"id","limit":"1"})
 if not r.is_success: raise RuntimeError("Could not verify MT5 connection")
 return bool(r.json())
def parse(x):
 s=x.upper(); symbol="BTCUSD" if "BTC" in s else "ETHUSD" if "ETH" in s else "EURUSD" if "EURUSD" in s or "EUR/USD" in s else "BTCUSD"
 tf="4h" if re.search(r"4\s*-?\s*HOUR",s) else "1h" if re.search(r"1\s*-?\s*HOUR",s) else "30m" if re.search(r"30\s*-?\s*MIN",s) else "15m" if re.search(r"15\s*-?\s*MIN",s) else "5m" if re.search(r"5\s*-?\s*MIN",s) else "1d" if re.search(r"1\s*-?\s*DAY|DAILY",s) else "15m"
 def g(p,d):
  m=re.search(p,s); return m.group(1) if m else d
 return {"symbol":symbol,"timeframe":tf,"lookback_days":int(g(r"(\d+)\s*DAYS?",90)),"rsi_period":int(g(r"RSI\s*\(?\s*(\d+)",14)),"rsi_entry_below":float(g(r"RSI.{0,100}(?:BELOW|LESS THAN|<)\s*(\d+(?:\.\d+)?)",30)),"rsi_exit_above":float(g(r"RSI.{0,100}(?:REACH(?:ES)?|ABOVE|GREATER THAN|>)\s*(\d+(?:\.\d+)?)",55)),"bollinger_period":int(g(r"BOLLINGER(?:\s+BANDS?)?\s*\(?\s*(\d+)",20)),"bollinger_std":float(g(r"BOLLINGER.{0,50}?(\d+(?:\.\d+)?)\s*(?:STD|STANDARD)",2)),"risk_pct":float(g(r"RISK\s*(?:OF\s*)?(\d+(?:\.\d+)?)\s*%",1)),"max_hold_hours":int(g(r"(\d+)\s*HOURS?",0)) or None}
def rsi(v,p):
 o=[None]*len(v)
 if len(v)<=p:return o
 ga=[max(v[i]-v[i-1],0) for i in range(1,len(v))]; lo=[max(v[i-1]-v[i],0) for i in range(1,len(v))]; ag=sum(ga[:p])/p; al=sum(lo[:p])/p
 for i in range(p,len(v)):
  if i>p: ag=(ag*(p-1)+ga[i-1])/p; al=(al*(p-1)+lo[i-1])/p
  o[i]=100 if al==0 else 100-100/(1+ag/al)
 return o
def bb(v,p,k):
 o=[None]*len(v)
 for i in range(p-1,len(v)):
  w=v[i-p+1:i+1];m=sum(w)/p;d=math.sqrt(sum((z-m)**2 for z in w)/p);o[i]=(m,m-k*d,m+k*d)
 return o
def bt(rows,s):
 c=[float(x["close"]) for x in rows];lo=[float(x["low"]) for x in rows];ts=[int(x["ts"]) for x in rows];rr=rsi(c,s["rsi_period"]);bands=bb(c,s["bollinger_period"],s["bollinger_std"]);entry=None;tr=[];rets=[];hold=s["max_hold_hours"]*3600000 if s.get("max_hold_hours") else None
 for i in range(1,len(rows)):
  if entry is None:
   if rr[i] is not None and bands[i] and rr[i]<s["rsi_entry_below"] and lo[i]<=bands[i][1]:entry=(c[i],ts[i])
   continue
  reason="rsi_exit" if rr[i] is not None and rr[i]>=s["rsi_exit_above"] else "time_exit" if hold and ts[i]-entry[1]>=hold else None
  if reason:
   pct=(c[i]-entry[0])/entry[0];rets.append(pct);tr.append({"entry_time":datetime.fromtimestamp(entry[1]/1000,timezone.utc).isoformat(),"exit_time":datetime.fromtimestamp(ts[i]/1000,timezone.utc).isoformat(),"entry_price":round(entry[0],8),"exit_price":round(c[i],8),"return_pct":round(pct*100,4),"risk_pct":s["risk_pct"],"exit_reason":reason});entry=None
 wins=[x for x in rets if x>0];loss=[x for x in rets if x<=0];eq=peak=1;dd=0
 for x in rets:eq*=1+x;peak=max(peak,eq);dd=max(dd,(peak-eq)/peak)
 mean=sum(rets)/len(rets) if rets else 0;var=sum((x-mean)**2 for x in rets)/len(rets) if rets else 0;gp=sum(wins);gl=abs(sum(loss))
 m={"total_trades":len(rets),"trade_count":len(rets),"win_rate":round(len(wins)*100/len(rets),2) if rets else 0,"total_return_pct":round((eq-1)*100,2),"max_drawdown_pct":round(dd*100,2),"sharpe_ratio":round(mean/math.sqrt(var)*math.sqrt(252),3) if var else 0,"profit_factor":round(gp/gl,3) if gl else 0,"risk_pct":s["risk_pct"],"final_equity_index":round(eq,6)}
 return {"metrics":m,"trades":tr[-100:]}
def yf_symbol(s): return {"EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"JPY=X","AUDUSD":"AUDUSD=X"}.get(s,s[:-3]+"-USD" if s.endswith("USD") else s)
def yi(tf): return {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"60m","4h":"60m","1d":"1d"}.get(tf,"15m")
def resample(a,w=14400000):
 b={}
 for x in a:b.setdefault(int(x["ts"])//w*w,[]).append(x)
 return [{"ts":k,"open":g[0]["open"],"high":max(z["high"] for z in g),"low":min(z["low"] for z in g),"close":g[-1]["close"]} for k,g in sorted(b.items())]
async def yahoo(s,tf,days):
 e=datetime.now(timezone.utc);st=e-timedelta(days=days);iv=yi(tf)
 if iv in {"1m","5m","15m","30m","60m"}:st=max(st,e-timedelta(days=59))
 async with httpx.AsyncClient(timeout=25,headers={"User-Agent":"Mozilla/5.0"}) as c:r=await c.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol(s)}",params={"period1":int(st.timestamp()),"period2":int(e.timestamp()),"interval":iv,"events":"history"})
 r.raise_for_status();q=r.json().get("chart",{}).get("result",[None])[0]
 if not q:raise RuntimeError("Yahoo Finance returned no market data")
 z=q["indicators"]["quote"][0];out=[]
 for i,t in enumerate(q.get("timestamp",[])):
  try:out.append({"ts":int(t)*1000,"open":float(z["open"][i]),"high":float(z["high"][i]),"low":float(z["low"][i]),"close":float(z["close"][i])})
  except (TypeError,ValueError,KeyError,IndexError):pass
 return resample(out) if tf=="4h" else out
async def mt5(uid,sid,s):
 now=datetime.now(timezone.utc);payload={"user_id":uid,"strategy_id":sid,"symbol":s["symbol"],"timeframe":s["timeframe"],"date_from":(now-timedelta(days=s["lookback_days"])).isoformat(),"date_to":now.isoformat(),"status":"queued"}
 async with httpx.AsyncClient(timeout=15) as c:r=await c.post(f"{SB}/rest/v1/mt5_bridge_jobs",headers=sh(),json=payload)
 if not r.is_success:raise RuntimeError("Could not queue MT5 market-data request")
 jid=r.json()[0]["id"];end=asyncio.get_running_loop().time()+90
 while asyncio.get_running_loop().time()<end:
  async with httpx.AsyncClient(timeout=10) as c:r=await c.get(f"{SB}/rest/v1/mt5_bridge_jobs",headers=sh(),params={"id":f"eq.{jid}","select":"status,rates,error","limit":"1"})
  row=r.json()[0] if r.is_success and r.json() else None
  if row and row["status"]=="complete":return [{"ts":int(x["time"])*1000,"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"])} for x in row["rates"]]
  if row and row["status"]=="failed":raise RuntimeError(row.get("error") or "MT5 bridge failed")
  await asyncio.sleep(2)
 raise RuntimeError("MT5 terminal did not respond in time")
async def run_pipeline(strategy_id,user_id,token):
 try:
  if not await connected(user_id,token):
   st=(await load(strategy_id,user_id,token)).get("spec") or {};st["pipeline_stage"]="awaiting_mt5_connection";st["pending_confirmation"]="mt5_connection";st["error"]=None;st["agents"]={**st.get("agents",{}),"research":"idle","backtest":"idle","indicator":"gated","paper":"gated","approval":"gated","live":"gated"};await save(strategy_id,user_id,token,st,"awaiting_mt5");return
  strategy=await load(strategy_id,user_id,token);st=strategy.get("spec") or {};s=parse(strategy.get("raw_strategy_text") or "");st["parsed_strategy"]=s;st["pipeline_stage"]="research_running";st["agents"]={**st.get("agents",{}),"research":"running","backtest":"queued","indicator":"queued","paper":"gated","approval":"gated","live":"gated"};await save(strategy_id,user_id,token,st,"research")
  try:rows=await mt5(user_id,strategy_id,s);source="MT5"
  except Exception as me:
   st["mt5_error"]=str(me)[:500]
   try:rows=await yahoo(s["symbol"],s["timeframe"],s["lookback_days"]);source="Yahoo Finance"
   except Exception:st["pipeline_stage"]="failed";st["error"]="Market data is temporarily unavailable. Please keep MetaTrader 5 open and connected, then retry.";st["agents"]={**st.get("agents",{}),"research":"failed","backtest":"failed"};await save(strategy_id,user_id,token,st,"failed");return
  if len(rows)<max(s["rsi_period"],s["bollinger_period"])+5:raise RuntimeError("Not enough market data for the requested strategy")
  st["pipeline_stage"]="backtest_running";st["agents"]={**st.get("agents",{}),"research":"complete","backtest":"running","indicator":"queued"};st["data_source"]=source;st["data_source_message"]="Market data is coming from your MetaTrader 5 account." if source=="MT5" else "The primary broker feed is unavailable, so the configured market-data fallback is being used.";st["bars_loaded"]=len(rows);await save(strategy_id,user_id,token,st,"backtesting")
  st["backtest"]={**bt(rows,s),"symbol":s["symbol"],"timeframe":s["timeframe"],"period_days":s["lookback_days"],"data_source":source};st["pipeline_stage"]="backtest_complete";st["agents"]={**st.get("agents",{}),"research":"complete","backtest":"complete","indicator":"complete","paper":"gated","approval":"gated","live":"gated"};st["pending_confirmation"]="backtest_review";await save(strategy_id,user_id,token,st,"backtest_complete")
 except Exception:
  try:
   st=(await load(strategy_id,user_id,token)).get("spec") or {};st["pipeline_stage"]="failed";st["error"]="The strategy run could not be completed. Please keep MetaTrader 5 open and connected, then retry.";st["agents"]={**st.get("agents",{}),"research":"failed","backtest":"failed"};await save(strategy_id,user_id,token,st,"failed")
  except Exception:pass
@api_router.get("/status/{strategy_id}")
async def status(strategy_id,user=Depends(get_current_user)):
 t=user.get("_access_token")
 if not t:raise HTTPException(401,"Missing access token")
 s=await load(strategy_id,user["id"],t);st=s.get("spec") or {};return {"strategy_id":strategy_id,"status":s.get("status"),"pipeline_stage":st.get("pipeline_stage"),"agents":st.get("agents",{}),"backtest":st.get("backtest"),"data_source":st.get("data_source"),"error":st.get("error")}
