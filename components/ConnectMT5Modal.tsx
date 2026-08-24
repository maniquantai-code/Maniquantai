"use client";

import { useState } from "react";
import { X, Copy, CheckCircle2, Monitor, ShieldCheck } from "lucide-react";
import { getAccessToken } from "@/lib/supabase";

export function ConnectMT5Modal({open,onClose,onConnected}:{open:boolean;onClose:()=>void;onConnected?:(accountId:string)=>void}){
 const [connecting,setConnecting]=useState(false);
 const [error,setError]=useState<string|null>(null);
 const [bridgeToken,setBridgeToken]=useState<string|null>(null);
 const [accountId,setAccountId]=useState<string|null>(null);
 const [copied,setCopied]=useState(false);
 if(!open)return null;

 async function readError(res:Response,fallback:string){
  const body=await res.json().catch(()=>null);
  return typeof body?.detail==="string"?body.detail:fallback;
 }

 async function connect(){
  setError(null);setConnecting(true);
  try{
   const token=await getAccessToken();
   if(!token)throw new Error("Please sign in again before connecting MetaTrader 5.");
   const h={Authorization:`Bearer ${token}`};
   const res=await fetch("/api/mt5-bridge/register",{method:"POST",headers:h});
   if(!res.ok)throw new Error(await readError(res,"Could not create the secure MT5 connection."));
   const data=await res.json();
   if(!data?.bridge_token)throw new Error("The secure MT5 connection token was not returned.");
   setBridgeToken(data.bridge_token);
   setAccountId(data.broker_account_id||null);
   if(data.broker_account_id)onConnected?.(data.broker_account_id);
  }catch(e){setError(e instanceof Error?e.message:"Could not connect MetaTrader 5.")}finally{setConnecting(false)}
 }

 async function copyToken(){
  if(!bridgeToken)return;
  await navigator.clipboard.writeText(bridgeToken);
  setCopied(true);setTimeout(()=>setCopied(false),1600);
 }

 return <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
  <div className="absolute inset-0 bg-black/60" onClick={onClose}/>
  <div className="relative w-full max-w-lg rounded-xl border border-border bg-bg-panel p-6 shadow-xl">
   <div className="mb-1 flex items-center justify-between"><h2 className="text-base font-semibold">Connect MetaTrader 5</h2><button onClick={onClose} className="text-text-muted hover:text-text" aria-label="Close"><X size={18}/></button></div>
   {!bridgeToken ? <>
    <p className="mt-2 text-sm leading-6 text-text-muted">Connect your own MT5 terminal to ManiQuantAI. Your broker password is <strong className="text-text">never entered into ManiQuantAI</strong>.</p>
    <div className="mt-5 grid gap-3 sm:grid-cols-3">
      <Info icon={<ShieldCheck size={16}/>} title="Secure token" text="A short-lived connection token links this terminal to your account."/>
      <Info icon={<Monitor size={16}/>} title="Your computer" text="MT5 runs on your Windows PC. No ManiQuantAI VPS is required."/>
      <Info icon={<CheckCircle2 size={16}/>} title="You control it" text="Keep AutoTrading enabled only when you want live execution."/>
    </div>
    <div className="mt-5 rounded-lg border border-border bg-bg-raised p-4 text-xs text-text-muted">
      <div className="font-medium text-text">How it works</div>
      <ol className="mt-2 space-y-1.5 list-decimal pl-4"><li>Click Connect and copy the generated token.</li><li>Open MetaTrader 5 and log into your broker account normally.</li><li>Start the ManiQuantAI Windows MT5 Bridge on the same PC and paste the token into its configuration.</li><li>Keep MT5 and the bridge running while automatic trading is enabled.</li></ol>
    </div>
    {error&&<div className="mt-3 rounded-lg border border-danger/25 bg-danger/5 p-3 text-sm text-danger">{error}</div>}
    <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-text-muted">Cancel</button><button onClick={connect} disabled={connecting} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg disabled:opacity-40">{connecting?"Creating secure connection…":"Connect MT5"}</button></div>
   </> : <div className="space-y-4">
    <div className="rounded-lg border border-accent/30 bg-accent-dim p-4"><p className="text-xs font-medium text-accent">MetaTrader 5 connection created</p><p className="mt-1 text-xs leading-5 text-text-muted">Account linking is complete on the ManiQuantAI side. Now connect the local bridge to the MT5 terminal where you are already logged into your broker.</p></div>
    <div><label className="mb-1 block text-xs text-text-muted">Bridge token</label><div className="flex gap-2"><code className="min-w-0 flex-1 break-all rounded-lg border border-border bg-bg px-3 py-2 text-[11px] text-text">{bridgeToken}</code><button onClick={copyToken} className="shrink-0 rounded-lg border border-border px-3 text-xs text-text-muted hover:text-text" aria-label="Copy bridge token">{copied?<CheckCircle2 size={16}/>:<Copy size={16}/>}</button></div></div>
    <div className="rounded-lg border border-border bg-bg-raised p-4 text-xs leading-5 text-text-muted"><strong className="text-text">Important:</strong> Do not send this token to anyone. It authorizes the local bridge to receive approved market-data and live-execution jobs for your ManiQuantAI account.</div>
    <div className="rounded-lg border border-border p-4 text-xs text-text-muted"><div className="font-medium text-text">Next step</div><div className="mt-1">Configure <code className="text-text">MANIQUANT_API_URL</code> and <code className="text-text">MT5_BRIDGE_TOKEN</code> in the ManiQuantAI Windows Bridge, then start it with MetaTrader 5 already open.</div>{accountId&&<div className="mt-2 text-[11px] text-text-faint">Connector: {accountId}</div>}</div>
    <button onClick={onClose} className="w-full rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg">Done</button>
   </div>}
  </div>
 </div>
}

function Info({icon,title,text}:{icon:React.ReactNode;title:string;text:string}){return <div className="rounded-lg border border-border bg-bg-raised p-3"><div className="flex items-center gap-2 text-accent">{icon}<span className="text-xs font-medium text-text">{title}</span></div><p className="mt-1.5 text-[11px] leading-4 text-text-faint">{text}</p></div>}
