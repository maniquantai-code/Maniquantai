"""Trading account connectors with encrypted secrets and generic broker APIs."""
from __future__ import annotations
import base64, hashlib, ipaddress, json, os, socket
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .auth import get_current_user

api_router=APIRouter(prefix="/api/broker-accounts",tags=["broker-accounts"])
SB=os.getenv("SUPABASE_URL","https://zuimeyynaarjsovnqilk.supabase.co").rstrip("/")
ANON=os.getenv("SUPABASE_ANON_KEY",os.getenv("SUPABASE_PUBLISHABLE_KEY","sb_publishable_Uf0ECWKVkKrH6pzedVbTOA_aNlp1J1X")).strip()
SERVICE=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()

def _fernet():
    key=os.getenv("FERNET_KEY","").strip()
    if not key:
        material=SERVICE or ANON
        if not material: raise HTTPException(503,"Trading account storage is not configured")
        key=base64.urlsafe_b64encode(hashlib.sha256(("maniquantai-trading-connector:"+material).encode()).digest()).decode()
    return Fernet(key.encode())

def _headers(token=None):
    key=SERVICE or ANON; bearer=SERVICE or (token or "").strip()
    if not key or not bearer: raise HTTPException(503,"Trading account storage is not configured")
    return {"apikey":key,"Authorization":f"Bearer {bearer}","Content-Type":"application/json","Prefer":"return=representation"}

def _token(user): return (user.get("access_token") or user.get("_access_token") or "").strip() or None
def _enc(x): return _fernet().encrypt(json.dumps(x,separators=(",",":")).encode()).decode()
def _dec(x): return json.loads(_fernet().decrypt(x.encode()).decode())

def _https(url):
    parsed=urlparse(url.replace("{symbol}","TEST").replace("{timeframe}","15m").replace("{start}","1970-01-01T00:00:00Z").replace("{end}","1970-01-02T00:00:00Z"))
    if parsed.scheme!="https" or not parsed.hostname: raise HTTPException(400,"Broker API URL must use HTTPS")
    if parsed.hostname.lower() in {"localhost","localhost.localdomain"} or parsed.hostname.lower().endswith(".local"): raise HTTPException(400,"Local broker API URLs are not allowed")
    try:
        for item in socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM):
            ip=ipaddress.ip_address(item[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: raise HTTPException(400,"Broker API hostname resolves to a private address")
    except socket.gaierror as e: raise HTTPException(400,"Broker API hostname could not be resolved") from e
    return url.strip()

class MT5ConnectRequest(BaseModel):
    login:int=Field(gt=0); password:str=Field(min_length=1,max_length=512); server:str=Field(min_length=1,max_length=200); label:str|None=Field(default=None,max_length=100)
class BrokerApiConnectRequest(BaseModel):
    broker_name:str=Field(min_length=1,max_length=100); label:str|None=Field(default=None,max_length=100)
    api_url:str=Field(min_length=1,max_length=2000); api_key:str=Field(min_length=1,max_length=1000); api_secret:str|None=Field(default=None,max_length=1000)
    auth_type:str=Field(default="bearer",pattern="^(bearer|x-api-key|basic)$")
    symbol_param:str=Field(default="symbol",max_length=80); timeframe_param:str=Field(default="interval",max_length=80)
    data_path:str=Field(default="",max_length=200); timestamp_path:str=Field(default="timestamp",max_length=100)
    open_path:str=Field(default="open",max_length=100); high_path:str=Field(default="high",max_length=100); low_path:str=Field(default="low",max_length=100); close_path:str=Field(default="close",max_length=100)

async def _primary(c,h,uid,account_id):
    await c.patch(f"{SB}/rest/v1/broker_accounts",headers=h,params={"user_id":f"eq.{uid}"},json={"is_primary":False})
    r=await c.patch(f"{SB}/rest/v1/broker_accounts",headers=h,params={"id":f"eq.{account_id}","user_id":f"eq.{uid}"},json={"is_primary":True})
    if not r.is_success: raise HTTPException(502,"Could not select this trading account")

@api_router.get("")
async def list_accounts(user=Depends(get_current_user)):
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.get(f"{SB}/rest/v1/broker_accounts",headers=_headers(_token(user)),params={"user_id":f"eq.{user['id']}","select":"id,connector_type,connector_name,label,created_at,last_verified_at,is_primary","order":"is_primary.desc,created_at.desc"})
    if not r.is_success: raise HTTPException(502,"Could not fetch trading accounts")
    return r.json()

@api_router.post("/mt5")
async def connect_mt5(req:MT5ConnectRequest,user=Depends(get_current_user)):
    uid=user["id"]; h=_headers(_token(user)); enc=_enc({"login":req.login,"password":req.password,"server":req.server.strip()}); payload={"user_id":uid,"connector_type":"mt5","connector_name":"MetaTrader 5","label":req.label,"encrypted_payload":enc,"last_verified_at":None}
    async with httpx.AsyncClient(timeout=15) as c:
        old=await c.get(f"{SB}/rest/v1/broker_accounts",headers=h,params={"user_id":f"eq.{uid}","connector_type":"eq.mt5","select":"id","limit":"1"})
        if not old.is_success: raise HTTPException(502,"Could not check the saved MT5 account")
        rows=old.json() or []
        if rows:
            aid=rows[0]["id"]; r=await c.patch(f"{SB}/rest/v1/broker_accounts",headers=h,params={"id":f"eq.{aid}","user_id":f"eq.{uid}"},json={"connector_name":"MetaTrader 5","label":req.label,"encrypted_payload":enc,"last_verified_at":None})
        else:
            r=await c.post(f"{SB}/rest/v1/broker_accounts",headers=h,json=payload); aid=(r.json() or [{}])[0].get("id") if r.is_success else None
        if not r.is_success or not aid: raise HTTPException(502,"Could not link this MetaTrader 5 account")
        prim=await c.get(f"{SB}/rest/v1/broker_accounts",headers=h,params={"user_id":f"eq.{uid}","select":"id","is_primary":"eq.true"})
        if prim.is_success and not prim.json(): await _primary(c,h,uid,aid)
    return {"broker_account_id":aid,"saved":True,"message":"MetaTrader 5 account linked successfully."}

@api_router.post("/api")
async def connect_api(req:BrokerApiConnectRequest,user=Depends(get_current_user)):
    uid=user["id"]; _https(req.api_url)
    enc=_enc({"api_url":req.api_url.strip(),"api_key":req.api_key,"api_secret":req.api_secret,"auth_type":req.auth_type,"symbol_param":req.symbol_param,"timeframe_param":req.timeframe_param,"data_path":req.data_path,"timestamp_path":req.timestamp_path,"open_path":req.open_path,"high_path":req.high_path,"low_path":req.low_path,"close_path":req.close_path})
    h=_headers(_token(user)); payload={"user_id":uid,"connector_type":"broker_api","connector_name":req.broker_name.strip(),"label":req.label,"encrypted_payload":enc,"last_verified_at":None,"is_primary":False}
    async with httpx.AsyncClient(timeout=15) as c:
        r=await c.post(f"{SB}/rest/v1/broker_accounts",headers=h,json=payload)
        if not r.is_success: raise HTTPException(502,"Could not save this broker API connection")
        aid=(r.json() or [{}])[0].get("id"); prim=await c.get(f"{SB}/rest/v1/broker_accounts",headers=h,params={"user_id":f"eq.{uid}","select":"id","is_primary":"eq.true"})
        if prim.is_success and not prim.json() and aid: await _primary(c,h,uid,aid)
    return {"broker_account_id":aid,"saved":True,"message":f"{req.broker_name.strip()} API connection saved successfully."}

@api_router.post("/{account_id}/primary")
async def make_primary(account_id:str,user=Depends(get_current_user)):
    uid=user["id"]; h=_headers(_token(user))
    async with httpx.AsyncClient(timeout=10) as c:
        check=await c.get(f"{SB}/rest/v1/broker_accounts",headers=h,params={"id":f"eq.{account_id}","user_id":f"eq.{uid}","select":"id","limit":"1"})
        if not check.is_success or not check.json(): raise HTTPException(404,"Trading account not found")
        await _primary(c,h,uid,account_id)
    return {"primary":True}

@api_router.delete("/{account_id}")
async def disconnect(account_id:str,user=Depends(get_current_user)):
    uid=user["id"]; h=_headers(_token(user))
    async with httpx.AsyncClient(timeout=10) as c:
        cur=await c.get(f"{SB}/rest/v1/broker_accounts",headers=h,params={"id":f"eq.{account_id}","user_id":f"eq.{uid}","select":"is_primary","limit":"1"})
        r=await c.delete(f"{SB}/rest/v1/broker_accounts",headers=h,params={"id":f"eq.{account_id}","user_id":f"eq.{uid}"})
        if not r.is_success: raise HTTPException(502,"Could not disconnect the trading account")
        if cur.is_success and cur.json() and cur.json()[0].get("is_primary"):
            nxt=await c.get(f"{SB}/rest/v1/broker_accounts",headers=h,params={"user_id":f"eq.{uid}","select":"id","order":"created_at.desc","limit":"1"})
            if nxt.is_success and nxt.json(): await _primary(c,h,uid,nxt.json()[0]["id"])
    return {"deleted":True}

async def fetch_broker_api_candles(account:dict,symbol:str,timeframe:str,days:int):
    cfg=_dec(account["encrypted_payload"]); template=cfg["api_url"]
    start=(datetime.now(timezone.utc)-__import__('datetime').timedelta(days=days)).isoformat(); end=datetime.now(timezone.utc).isoformat()
    url=template.format(symbol=symbol,timeframe=timeframe,start=start,end=end)
    params={cfg["symbol_param"]:symbol,cfg["timeframe_param"]:timeframe}
    headers={"Accept":"application/json","User-Agent":"ManiQuantAI/1.0"}
    if cfg["auth_type"]=="bearer": headers["Authorization"]=f"Bearer {cfg['api_key']}"
    elif cfg["auth_type"]=="x-api-key": headers["X-API-Key"]=cfg["api_key"]
    else: headers["Authorization"]="Basic "+base64.b64encode(f"{cfg['api_key']}:{cfg.get('api_secret') or ''}".encode()).decode()
    if cfg.get("api_secret") and cfg["auth_type"]!="basic": headers["X-API-Secret"]=cfg["api_secret"]
    async with httpx.AsyncClient(timeout=30,headers=headers) as c:
        r=await c.get(url,params=params); r.raise_for_status(); payload=r.json()
    data=payload
    for part in filter(None,cfg["data_path"].split('.')): data=data[int(part)] if isinstance(data,list) else data[part]
    if isinstance(data,dict): data=data.get("candles") or data.get("rates") or data.get("data") or []
    if not isinstance(data,list) or not data: raise RuntimeError("Broker API returned no candle data")
    def get(row,path,index):
        if isinstance(row,dict):
            v=row
            for p in path.split('.'): v=v[p]
            return v
        return row[index]
    out=[]
    for row in data:
        try:
            ts=get(row,cfg["timestamp_path"],0); ts=int(datetime.fromisoformat(ts.replace('Z','+00:00')).timestamp()*1000) if isinstance(ts,str) else int(float(ts)*(1000 if float(ts)<10_000_000_000 else 1))
            out.append({"ts":ts,"open":float(get(row,cfg["open_path"],1)),"high":float(get(row,cfg["high_path"],2)),"low":float(get(row,cfg["low_path"],3)),"close":float(get(row,cfg["close_path"],4))})
        except (KeyError,IndexError,TypeError,ValueError): continue
    if not out: raise RuntimeError("Broker API response could not be mapped to OHLC candles")
    return sorted(out,key=lambda x:int(x["ts"]))

def decrypt_connector(payload:str): return _dec(payload)
