"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, ImagePlus, X } from "lucide-react";
import { getAccessToken, supabase } from "@/lib/supabase";

export interface ChatMessage { role: "user" | "assistant"; content: string; timestamp: string; image?: string }
type Gate = "research" | "backtest" | "approval" | "paper" | "live" | null;

const now = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const norm = (v: string) => v.trim().toLowerCase().replace(/\s+/g, " ");
const wantsPaper = (v: string) => /paper\s+trad(e|ing)/i.test(v);
const wantsLive = (v: string) => /live\s+trad(e|ing)|start\s+live/i.test(v);

function gateFromPending(v?: string | null): Gate {
  if (v === "research_start") return "research";
  if (v === "backtest" || v === "backtest_review") return "backtest";
  if (v === "approval") return "approval";
  if (v === "paper_launch") return "paper";
  if (v === "live_approval") return "live";
  return null;
}

export function ChatPanel({ strategyId, initialMessages, onboarding = false }: { strategyId?: string; initialMessages?: ChatMessage[]; onboarding?: boolean }) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages ?? []);
  const [input, setInput] = useState("");
  const [image, setImage] = useState<string>();
  const [sending, setSending] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(!!strategyId);
  const [gate, setGate] = useState<Gate>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const persist = async (role: "user" | "assistant", content: string) => {
    if (!strategyId || !content.trim()) return;
    const { error } = await supabase.from("chat_messages").insert({ strategy_id: strategyId, role, content: content.trim() });
    if (error) console.warn("Could not persist chat message", error.message);
  };

  const addAssistant = (content: string) => {
    setMessages(m => [...m, { role: "assistant", content, timestamp: now() }]);
    void persist("assistant", content);
  };

  useEffect(() => {
    let mounted = true;
    (async () => {
      if (!strategyId) { setHistoryLoading(false); return; }
      setHistoryLoading(true);
      const { data, error } = await supabase.from("chat_messages").select("role,content,created_at").eq("strategy_id", strategyId).order("created_at", { ascending: true }).limit(500);
      if (!mounted) return;
      if (!error && data?.length) setMessages(data.map((m: any) => ({ role: m.role, content: m.content, timestamp: new Date(m.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) })));
      else if (!error && initialMessages?.length) setMessages(initialMessages);
      try {
        const token = await getAccessToken();
        const r = await fetch(`/api/pipeline/status/${strategyId}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
        if (r.ok) {
          const p = await r.json();
          const g = gateFromPending(p.pending_confirmation);
          if (g) setGate(g);
        }
      } catch { /* status restoration is best effort */ }
      if (mounted) setHistoryLoading(false);
    })();
    return () => { mounted = false };
  }, [strategyId]);

  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [messages]);

  useEffect(() => {
    if (!onboarding || messages.length) return;
    let mounted = true;
    supabase.auth.getUser().then(({ data }) => {
      if (!mounted) return;
      const u = data.user; const md = (u?.user_metadata ?? {}) as Record<string, unknown>;
      const name = String(md.full_name || md.name || md.first_name || u?.email?.split("@")[0] || "there").trim();
      setMessages([{ role: "assistant", content: `Hello ${name} 👋\n\nWelcome to ManiQuantAI. I'm your AI trading strategy partner. Tell me what you want to trade and how you want to trade it.`, timestamp: now() }]);
    });
    return () => { mounted = false };
  }, [onboarding, messages.length]);

  const acceptImage = (file?: File) => {
    if (!file || !file.type.startsWith("image/")) return;
    if (file.size > 8 * 1024 * 1024) { addAssistant("That chart image is larger than 8 MB. Please use a smaller PNG, JPG, or WebP screenshot."); return; }
    const reader = new FileReader(); reader.onload = () => setImage(String(reader.result)); reader.readAsDataURL(file);
  };

  const onPaste = (e: React.ClipboardEvent) => {
    const item = Array.from(e.clipboardData.items).find(i => i.type.startsWith("image/"));
    if (item) { e.preventDefault(); acceptImage(item.getAsFile() ?? undefined); }
  };

  async function backendMessage(content: string, attached?: string, showUser = true) {
    if (!strategyId) throw new Error("Create or select a strategy first so I can analyse it.");
    const token = await getAccessToken();
    const display = attached ? `${content}\n\n[Chart screenshot attached]` : content;
    if (showUser) {
      setMessages(m => [...m, { role: "user", content, timestamp: now(), image: attached }]);
      await persist("user", display);
    }

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ strategy_id: strategyId, message: content, image: attached || null })
    });
    if (!res.ok) {
      const raw = await res.text(); let detail = raw;
      try { const j = JSON.parse(raw); detail = j.detail || j.message || raw; } catch { /* text error */ }
      throw new Error(String(detail).slice(0, 300));
    }
    if (!res.body) throw new Error("AI service returned no response body.");

    // CRITICAL: acquire the reader before consuming the body. A ReadableStream
    // can only have one reader. Never call res.text()/res.json() and then getReader().
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const contentType = (res.headers.get("content-type") || "").toLowerCase();
    let raw = "";
    let buffer = "";
    let text = "";
    let final = "";
    let added = false;
    const ts = now();
    const upsert = (next: string) => {
      final = next;
      setMessages(m => { const base = added ? m.slice(0, -1) : m; added = true; return [...base, { role: "assistant", content: next, timestamp: ts }]; });
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      if (contentType.includes("application/json")) raw += chunk;
      else {
        buffer += chunk;
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const event of events) {
          const line = event.split("\n").find(x => x.startsWith("data:"));
          if (!line) continue;
          let p: any; try { p = JSON.parse(line.slice(5).trim()); } catch { continue; }
          if (p.type === "delta") { text += p.content ?? ""; if (text) upsert(text); }
          else if (p.type === "error") throw new Error(p.message ?? "AI service failed");
        }
      }
    }
    if (contentType.includes("application/json")) {
      let p: any; try { p = JSON.parse(raw); } catch { throw new Error("The AI service returned an invalid response."); }
      final = p.content || p.message || "The request completed.";
      setMessages(m => [...m, { role: "assistant", content: final, timestamp: now() }]);
      await persist("assistant", final);
      if (p.action === "confirm_research") setGate("research");
      else if (p.action === "confirm_backtest") setGate("backtest");
      else if (p.action === "approval") setGate("approval");
      else if (p.action === "paper_ready") setGate("paper");
      else if (p.action === "live_ready" || p.action === "request_live_approval") setGate("live");
      else if (p.action === "paper_started" || p.action === "live_running") setGate(null);
      return final;
    }
    if (!final) upsert("The AI completed the request but returned no text. Check the strategy status for agent progress.");
    if (final) await persist("assistant", final);
    return final;
  }

  async function submitGate(choice: "yes" | "no") {
    if (!strategyId || !gate || sending) return;
    const current = gate;
    setSending(true);
    setMessages(m => [...m, { role: "user", content: choice === "yes" ? "Yes" : "No", timestamp: now() }]);
    await persist("user", choice === "yes" ? "Yes" : "No");
    try {
      if (choice === "no") { setGate(null); addAssistant(current === "live" ? "Okay. Live trading remains locked. No live order was submitted." : "Okay. This stage is paused. Nothing has been executed."); return; }
      setGate(null);
      addAssistant(current === "paper" ? "Starting paper trading…" : current === "live" ? "Approving live trading…" : "Processing your approval…");
      try {
        await backendMessage(current === "approval" ? "approve" : current === "live" ? "approve live" : "yes", undefined, false);
      } catch (e) {
        // Restore exactly one gate so retry is possible; never append another prompt.
        setGate(current);
        addAssistant(`I couldn't complete that action.\n\n${e instanceof Error ? e.message : "Please try again."}`);
      }
    } finally { setSending(false); }
  }

  async function sendMessage() {
    const content = input.trim(); if ((!content && !image) || sending) return;
    setInput(""); const attached = image; setImage(undefined);
    if (wantsLive(content)) { setMessages(m => [...m, { role: "user", content, timestamp: now(), image: attached }]); await persist("user", content); setGate("live"); addAssistant("The strategy has reached the live gate. **Do you approve live trading?**"); return; }
    if (wantsPaper(content) && !gate) { setMessages(m => [...m, { role: "user", content, timestamp: now(), image: attached }]); await persist("user", content); setGate("paper"); addAssistant("Paper trading is ready. **Start paper trading?**"); return; }
    setSending(true);
    try { await backendMessage(content || "Please analyse this chart screenshot.", attached, true); }
    catch (e) { addAssistant(`I couldn't complete that request.\n\n${e instanceof Error ? e.message : "AI service request failed."}`); }
    finally { setSending(false); }
  }

  const prompt = gate === "research" ? "Start Research Agent?" : gate === "backtest" ? "Start Deterministic Backtest Agent?" : gate === "approval" ? "Approve strategy for paper trading?" : gate === "paper" ? "Start Paper Trading?" : gate === "live" ? "Approve Live Trading?" : "";

  return <div className="flex h-full min-h-[520px] flex-col lg:border-l lg:border-border">
    <div className="flex items-center justify-between border-b border-border px-5 py-3"><span className="text-xs uppercase tracking-wide text-text-muted">ManiQuant AI</span><span className="flex items-center gap-1.5 rounded-md border border-border bg-bg-raised px-2 py-0.5 text-xs text-text-muted"><span className="h-1.5 w-1.5 rounded-full bg-accent"/>Ready</span></div>
    <div ref={scrollRef} onPaste={onPaste} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); acceptImage(e.dataTransfer.files?.[0]); }} className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
      {historyLoading ? <div className="py-6 text-center text-xs text-text-faint">Loading chat history…</div> : messages.map((m, i) => <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}><div className={["max-w-[90%] rounded-lg px-4 py-3 text-sm leading-relaxed", m.role === "user" ? "bg-accent-dim text-text border border-accent/20" : "bg-bg-panel text-text border border-border"].join(" ")}>{m.image && <img src={m.image} alt="Attached trading chart" className="mb-3 max-h-72 max-w-full rounded-md border border-border object-contain"/>}<p className="whitespace-pre-line">{m.content}</p><span className="mt-2 block text-[10px] text-text-faint">{m.role === "user" ? "You" : "ManiQuant AI"} · {m.timestamp}</span></div></div>)}
      {gate && <div className="rounded-lg border border-border bg-bg-panel p-3"><div className="mb-2 text-xs font-medium text-text">{prompt}</div><div className="flex gap-2"><button onClick={() => void submitGate("yes")} disabled={sending} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-bg disabled:opacity-50">{sending ? "Working…" : "Yes"}</button><button onClick={() => void submitGate("no")} disabled={sending} className="rounded-md border border-border bg-bg-raised px-4 py-2 text-sm text-text disabled:opacity-50">No</button></div></div>}
      {sending && <div className="flex justify-start"><div className="rounded-lg border border-border bg-bg-panel px-4 py-2.5 text-sm text-text-faint">Working…</div></div>}
    </div>
    <div className="border-t border-border p-4"><div className="flex items-center gap-2 rounded-lg border border-border bg-bg-panel px-3 py-2"><input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={e => acceptImage(e.target.files?.[0])}/><button type="button" onClick={() => fileRef.current?.click()} disabled={sending || !strategyId} className="flex h-7 w-7 items-center justify-center rounded-md text-text-muted hover:bg-bg-raised disabled:opacity-40" aria-label="Attach chart screenshot"><ImagePlus size={17}/></button><input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void sendMessage(); } }} placeholder="Tell ManiQuant AI what you want to trade…" className="flex-1 bg-transparent text-sm text-text placeholder:text-text-faint outline-none"/><button onClick={() => void sendMessage()} disabled={sending || !strategyId || (!input.trim() && !image)} className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-bg disabled:opacity-40" aria-label="Send message"><ArrowUp size={14}/></button></div>{image && <div className="mt-2 flex items-center gap-2 rounded-md border border-border bg-bg-raised p-2"><img src={image} alt="Chart preview" className="h-16 w-24 rounded object-cover"/><span className="flex-1 text-xs text-text-muted">Chart screenshot attached</span><button type="button" onClick={() => setImage(undefined)} className="rounded p-1 text-text-muted" aria-label="Remove image"><X size={15}/></button></div>}</div>
  </div>;
}
