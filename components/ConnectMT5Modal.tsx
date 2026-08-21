"use client";
import { useState } from "react";
import { X } from "lucide-react";
import { getAccessToken } from "@/lib/supabase";

export function ConnectMT5Modal({open,onClose,onConnected}:{open:boolean;onClose:()=>void;onConnected?:(accountId:string)=>void}){
 const [login,setLogin]=useState("");
 const [password,setPassword]=useState("");
 const [server,setServer]=useState("");
 const [label,setLabel]=useState("");
 const [connecting,setConnecting]=useState(false);
 const [error,setError]=useState<string|null>(null);
 const [saved,setSaved]=useState(false);
 const [bridgePending,setBridgePending]=useState(false);
 const [bridgeToken,setBridgeToken]=useState<string|null>(null);
 if(!open)return null;

 async function readError(res:Response,fallback:string){
  const body=await res.json().catch(()=>null);
  return typeof body?.detail==="string"?body.detail:fallback;
 }

 async function handleSubmit(e:React.FormEvent){
  e.preventDefault();
  setError(null);
  const loginNumber=parseInt(login,10);
  if(!loginNumber||!password||!server){setError("Enter your MT5 account number, password, and server.");return}
  setConnecting(true);
  try{
   const token=await getAccessToken();
   if(!token)throw new Error("Please sign in again before connecting your MetaTrader 5 account.");
   const h={"Content-Type":"application/json",Authorization:`Bearer ${token}`};
   const res=await fetch("/api/broker-accounts/mt5",{method:"POST",headers:h,body:JSON.stringify({login:loginNumber,password,server:server.trim(),label:label||undefined})});
   if(!res.ok)throw new Error(await readError(res,"We couldn't save the MT5 connection right now. Please try again."));
   const data=await res.json();
   if(!data?.broker_account_id)throw new Error("The MT5 account was not returned by the server. Please try again.");

   // Saving the account is the successful connection step. Bridge registration
   // is intentionally best-effort so a bridge outage never makes a saved
   // trading account look like it failed to connect.
   setSaved(true);
   onConnected?.(data.broker_account_id);
   setLogin("");setPassword("");setServer("");setLabel("");

   try{
    setBridgePending(true);
    const reg=await fetch("/api/mt5-bridge/register",{method:"POST",headers:h});
    if(reg.ok){
      const bridge=await reg.json().catch(()=>null);
      if(bridge?.bridge_token)setBridgeToken(bridge.bridge_token);
    }
   }catch{
    // The account remains saved. The local bridge can be configured later.
   }finally{
    setBridgePending(false);
   }
  }catch(e){setError(e instanceof Error?e.message:"We couldn't complete the MT5 connection. Please try again.")}finally{setConnecting(false)}
 }

 return <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
  <div className="absolute inset-0 bg-black/60" onClick={onClose}/>
  <div className="relative w-full max-w-md rounded-lg border border-border bg-bg-panel p-6">
   <div className="mb-1 flex items-center justify-between"><h2 className="text-base font-semibold">Connect MetaTrader 5</h2><button onClick={onClose} className="text-text-muted hover:text-text" aria-label="Close"><X size={18}/></button></div>
   <p className="mb-4 text-xs text-text-faint">Use the same account details as your MT5 terminal. Keep MetaTrader 5 open on the Windows PC running the ManiQuantAI bridge.</p>
   {saved?
    <div className="space-y-3">
     <div className="rounded-lg border border-accent/30 bg-accent-dim p-3"><p className="text-xs font-medium text-accent">MT5 account saved successfully</p><p className="mt-1 text-xs text-text-muted">Your account is now linked to ManiQuantAI. Research and backtesting can use this account's market data.</p></div>
     {bridgeToken ?
      <div className="rounded-lg border border-border bg-bg-raised p-3"><p className="text-xs font-medium text-text">Bridge setup</p><p className="mt-1 text-xs text-text-muted">Keep MetaTrader 5 open and run the ManiQuantAI MT5 Bridge on the same Windows PC. Copy this token into its configuration:</p><code className="mt-2 block break-all rounded bg-bg p-2 text-[11px] text-text">{bridgeToken}</code></div>
      : bridgePending ?
      <div className="rounded-lg border border-border bg-bg-raised p-3"><p className="text-xs font-medium text-text">Finishing bridge setup…</p><p className="mt-1 text-xs text-text-muted">Your MT5 account is already saved. The bridge can finish connecting in the background.</p></div>
      :
      <div className="rounded-lg border border-border bg-bg-raised p-3"><p className="text-xs font-medium text-text">Bridge setup can be completed next</p><p className="mt-1 text-xs text-text-muted">Keep MetaTrader 5 open on the Windows PC running the ManiQuantAI MT5 Bridge. Your saved account is not affected if the bridge is temporarily unavailable.</p></div>}
     <button onClick={onClose} className="w-full rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg">Done</button>
    </div>
    :<form onSubmit={handleSubmit} className="space-y-3">
     <div><label className="mb-1 block text-xs text-text-muted">Login (account number)</label><input type="text" inputMode="numeric" value={login} onChange={e=>setLogin(e.target.value.replace(/\D/g,""))} placeholder="12345678" className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text"/></div>
     <div><label className="mb-1 block text-xs text-text-muted">Password</label><input type="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="Your MT5 password" className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text"/></div>
     <div><label className="mb-1 block text-xs text-text-muted">Server</label><input type="text" value={server} onChange={e=>setServer(e.target.value)} placeholder="e.g. Exness-Real" className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text"/></div>
     <div><label className="mb-1 block text-xs text-text-muted">Nickname (optional)</label><input type="text" value={label} onChange={e=>setLabel(e.target.value)} placeholder="My MT5 account" className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text"/></div>
     {error&&<div className="rounded-lg border border-danger/25 bg-danger/5 p-3 text-sm text-danger">{error}</div>}
     <div className="flex justify-end gap-2 pt-1"><button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-text-muted">Cancel</button><button type="submit" disabled={connecting} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg disabled:opacity-40">{connecting?"Connecting…":"Connect account"}</button></div>
    </form>}
  </div>
 </div>
}
