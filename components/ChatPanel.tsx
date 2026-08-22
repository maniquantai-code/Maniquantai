"use client";
import { useState, useRef, useEffect } from "react";
import { ArrowUp } from "lucide-react";
import { getAccessToken, supabase } from "@/lib/supabase";

export interface ChatMessage { role: "user" | "assistant"; content: string; timestamp: string; }
function now(){return new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"});}
function dbTime(value:string){try{return new Date(value).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"});}catch{return now();}}
function norm(value:string){return value.trim().toLowerCase().replace(/\s+/g," ");}
function wantsPaper(value:string){const v=norm(value);return v.includes("paper trading")||v.includes("paper trade");}

export function ChatPanel({strategyId,initialMessages,onboarding=false}:{strategyId?:string;initialMessages?:ChatMessage[];onboarding?:boolean}){
 const [messages,setMessages]=useState<ChatMessage[]>(initialMessages??[]);
 const [input,setInput]=useState(""); const [sending,setSending]=useState(false);
 const [historyLoading,setHistoryLoading]=useState(!!strategyId);
 const [paperChoicePending,setPaperChoicePending]=useState(false);
 const [liveApprovalPending,setLiveApprovalPending]=useState(false);
 const scrollRef=useRef<HTMLDivElement>(null);

 useEffect(()=>{let mounted=true;
   async function loadHistory(){
     if(!strategyId){setHistoryLoading(false);return;}
     setHistoryLoading(true);
     const {data,error}=await supabase.from("chat_messages").select("role,content,created_at").eq("strategy_id",strategyId).order("created_at",{ascending:true}).order("id",{ascending:true}).limit(500);
     if(!mounted)return;
     if(!error&&data?.length){setMessages(data.map((m:any)=>({role:m.role,content:m.content,timestamp:dbTime(m.created_at)})));}
     else if(!error&&initialMessages?.length){setMessages(initialMessages);}
     setHistoryLoading(false);
   }
   loadHistory(); return()=>{mounted=false};
 },[strategyId]);

 useEffect(()=>{if(!onboarding||messages.length)return;let mounted=true;supabase.auth.getUser().then(({data})=>{if(!mounted)return;const u=data.user;const md=(u?.user_metadata??{}) as Record<string,unknown>;const name=String(md.full_name||md.name||md.first_name||u?.email?.split("@")[0]||"there").trim();setMessages([{role:"assistant",content:`Hello ${name} 👋\n\nWelcome to ManiQuantAI. I'm your AI trading strategy partner. Tell me what you want to trade and how you want to trade it.\n\nFor example:\n“Create a BTC/USD 15-minute long-only EMA 9/21 crossover strategy with a 1% stop loss and 2% take profit. Backtest it for the last 90 days.”\n\nI'll guide the strategy through research, deterministic backtesting, indicator verification, human approval, paper trading, and live eligibility.\n\nWhat would you like to build today?`,timestamp:now()}]);});return()=>{mounted=false};},[onboarding,messages.length]);
 useEffect(()=>{scrollRef.current?.scrollTo({top:scrollRef.current.scrollHeight,behavior:"smooth"})},[messages]);

 async function persist(role:"user"|"assistant",content:string){if(!strategyId||!content.trim())return;const {error}=await supabase.from("chat_messages").insert({strategy_id:strategyId,role,content:content.trim()});if(error)console.warn("Could not persist chat message",error.message);}
 function addAssistant(content:string){const msg={role:"assistant" as const,content,timestamp:now()};setMessages(m=>[...m,msg]);void persist("assistant",content);}

 async function backendMessage(content:string, showUser=true){
   const token=await getAccessToken();
   if(!strategyId)throw new Error("Create or select a strategy first so I can analyse it.");
   if(showUser){setMessages(m=>[...m,{role:"user",content,timestamp:now()}]);await persist("user",content);}
   const assistantTimestamp=now();let finalAssistant="";
   const res=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json",Accept:"text/event-stream",...(token?{Authorization:`Bearer ${token}`}:{})},body:JSON.stringify({strategy_id:strategyId,message:content})});
   if(!res.ok){const detail=await res.text();throw new Error(`AI service returned ${res.status}: ${detail.slice(0,220)}`)}
   const contentType=res.headers.get("content-type")||"";
   if(contentType.includes("application/json")){
     const payload=await res.json();finalAssistant=payload.content||payload.message||"The request completed.";
     setMessages(m=>[...m,{role:"assistant",content:finalAssistant,timestamp:assistantTimestamp}]);await persist("assistant",finalAssistant);return finalAssistant;
   }
   if(!res.body)throw new Error("AI service returned no response body.");
   const reader=res.body.getReader();const decoder=new TextDecoder();let buffer="",text="",added=false;
   const upsert=(next:string)=>{finalAssistant=next;setMessages(current=>{const base=added?current.slice(0,-1):current;added=true;return[...base,{role:"assistant",content:next,timestamp:assistantTimestamp}]})};
   while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const events=buffer.split("\n\n");buffer=events.pop()??"";for(const event of events){const line=event.split("\n").find(x=>x.startsWith("data:"));if(!line)continue;let payload:any;try{payload=JSON.parse(line.slice(5).trim())}catch{continue}if(payload.type==="delta"){text+=payload.content??"";if(text)upsert(text)}else if(payload.type==="error")throw new Error(payload.message??"AI service failed");}}
   if(buffer.trim()){const line=buffer.split("\n").find(x=>x.startsWith("data:"));if(line){try{const payload=JSON.parse(line.slice(5).trim());if(payload.type==="delta"){text+=payload.content??"";if(text)upsert(text)}else if(payload.type==="error")throw new Error(payload.message??"AI service failed")}catch(e){if(e instanceof Error&&e.message!=="Unexpected end of JSON input")throw e}}}
   if(!added)upsert("The AI completed the request but returned no text. The strategy pipeline may still be running; check the strategy status for agent progress.");
   if(finalAssistant)await persist("assistant",finalAssistant);
   return finalAssistant;
 }

 async function paperDecision(decision:"yes"|"no"|"live_yes"|"live_no"){
   if(!strategyId)return;
   const choiceLabel=decision==="yes"?"Yes":decision==="no"?"No":decision==="live_yes"?"Approve live":"No";
   setMessages(m=>[...m,{role:"user",content:choiceLabel,timestamp:now()}]);await persist("user",choiceLabel);
   setSending(true);
   try{
     const token=await getAccessToken();
     const res=await fetch("/api/paper-decision",{method:"POST",headers:{"Content-Type":"application/json",...(token?{Authorization:`Bearer ${token}`}:{})},body:JSON.stringify({strategy_id:strategyId,decision})});
     const payload=await res.json();
     if(!res.ok)throw new Error(payload.detail||payload.message||"Could not update the trading gate.");
     if(decision==="yes"){
       setPaperChoicePending(false);
       addAssistant(payload.message||"Yes selected. I’ll start paper trading now.");
       await backendMessage("do paper trading",false);
     } else if(decision==="no"){
       setPaperChoicePending(false);setLiveApprovalPending(true);
       addAssistant(payload.message||"Paper trading will be skipped. Do you explicitly approve live trading?");
     } else if(decision==="live_yes"){
       setLiveApprovalPending(false);
       addAssistant(payload.message||"Live trading approved. Proceeding to the live-execution gate.");
       await backendMessage("do live trade",false);
     } else {
       setLiveApprovalPending(true);addAssistant(payload.message||"Live trading remains locked. No live order was submitted.");
     }
   }catch(e){addAssistant(`I couldn't update the trading gate.\n\n${e instanceof Error?e.message:"Request failed."}`)}finally{setSending(false)}
 }

 async function sendMessage(){
   if(!input.trim()||sending)return;const content=input.trim();setInput("");
   if(wantsPaper(content)&&!paperChoicePending&&!liveApprovalPending){
     setMessages(m=>[...m,{role:"user",content,timestamp:now()}]);await persist("user",content);
     setPaperChoicePending(true);
     addAssistant("Before I start paper trading, do you want to run the strategy in paper mode first? This is a required choice before live execution.\n\n**Yes** — run paper trading first.\n**No** — skip paper trading and request separate live-trading approval.");
     return;
   }
   setSending(true);try{await backendMessage(content,true)}catch(e){const errorText=`I couldn't complete that request.\n\n${e instanceof Error?e.message:"AI service request failed."}`;setMessages(m=>[...m,{role:"assistant",content:errorText,timestamp:now()}]);await persist("assistant",errorText)}finally{setSending(false)}
 }

 return <div className="flex h-full min-h-[520px] flex-col lg:border-l lg:border-border">
  <div className="flex items-center justify-between border-b border-border px-5 py-3"><span className="text-xs uppercase tracking-wide text-text-muted">ManiQuant AI</span><span className="flex items-center gap-1.5 rounded-md border border-border bg-bg-raised px-2 py-0.5 text-xs text-text-muted"><span className="h-1.5 w-1.5 rounded-full bg-accent"/>Ready</span></div>
  <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
   {historyLoading?<div className="text-center text-xs text-text-faint py-6">Loading chat history…</div>:messages.map((m,i)=><div key={i} className={m.role==="user"?"flex justify-end":"flex justify-start"}><div className={["max-w-[90%] whitespace-pre-line rounded-lg px-4 py-3 text-sm leading-relaxed",m.role==="user"?"bg-accent-dim text-text border border-accent/20":"bg-bg-panel text-text border border-border"].join(" ")}><p>{m.content}</p><span className="mt-2 block text-[10px] text-text-faint">{m.role==="user"?"You":"ManiQuant AI"} · {m.timestamp}</span></div></div>)}
   {paperChoicePending&&<div className="flex gap-2"><button onClick={()=>paperDecision("yes")} disabled={sending} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-bg disabled:opacity-50">Yes</button><button onClick={()=>paperDecision("no")} disabled={sending} className="rounded-md border border-border bg-bg-panel px-4 py-2 text-sm text-text disabled:opacity-50">No</button></div>}
   {liveApprovalPending&&<div className="flex gap-2"><button onClick={()=>paperDecision("live_yes")} disabled={sending} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-bg disabled:opacity-50">Approve live</button><button onClick={()=>paperDecision("live_no")} disabled={sending} className="rounded-md border border-border bg-bg-panel px-4 py-2 text-sm text-text disabled:opacity-50">No</button></div>}
   {sending&&<div className="flex justify-start"><div className="rounded-lg border border-border bg-bg-panel px-4 py-2.5 text-sm text-text-faint">Analysing…</div></div>}
  </div>
  <div className="border-t border-border p-4"><div className="flex items-center gap-2 rounded-lg border border-border bg-bg-panel px-3 py-2"><input value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&sendMessage()} placeholder="Tell ManiQuant AI what you want to trade…" className="flex-1 bg-transparent text-sm text-text placeholder:text-text-faint outline-none"/><button onClick={sendMessage} disabled={sending||!strategyId} className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-bg disabled:opacity-40" aria-label="Send message"><ArrowUp size={14}/></button></div></div>
 </div>;
}
