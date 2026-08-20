"use client";
import { useState, useRef, useEffect } from "react";
import { ArrowUp } from "lucide-react";
import { getAccessToken, supabase } from "@/lib/supabase";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

function now() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function ChatPanel({ strategyId, initialMessages, onboarding = false }: { strategyId?: string; initialMessages?: ChatMessage[]; onboarding?: boolean }) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages ?? []);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!onboarding || messages.length) return;
    let mounted = true;
    supabase.auth.getUser().then(({ data }) => {
      if (!mounted) return;
      const user = data.user;
      const metadata = (user?.user_metadata ?? {}) as Record<string, unknown>;
      const name = String(metadata.full_name || metadata.name || metadata.first_name || user?.email?.split("@")[0] || "there").trim();
      setMessages([{
        role: "assistant",
        content: `Hello ${name} 👋\n\nWelcome to ManiQuantAI. I'm your AI trading strategy partner, and I'm here to help you turn your trading ideas into structured, testable strategies.\n\nYou can simply tell me what you want to trade and how you want to trade it. For example:\n\n“Create a BTC/USD 15-minute long-only EMA 9/21 crossover strategy with a 1% stop loss and 2% take profit. Backtest it for the last 90 days.”\n\nI'll guide you through Strategy → Backtest → Validation → Human Approval → Paper Trading → Live when eligible. You stay in control at every important step.\n\nWhat would you like to build today?`,
        timestamp: now(),
      }]);
    });
    return () => { mounted = false; };
  }, [onboarding, messages.length]);

  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [messages]);

  async function sendMessage() {
    if (!input.trim() || sending) return;
    const userMsg = { role: "user" as const, content: input.trim(), timestamp: now() };
    setMessages((m) => [...m, userMsg]); setInput(""); setSending(true);
    const assistantTimestamp = now();
    try {
      const token = await getAccessToken();
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ strategy_id: strategyId ?? null, message: userMsg.content }),
      });
      if (!res.ok || !res.body) throw new Error(`Chat request failed (${res.status})`);
      const reader = res.body.getReader(); const decoder = new TextDecoder(); let buffer = ""; let text = ""; let added = false;
      const upsert = (content: string) => setMessages((current) => { const base = added ? current.slice(0, -1) : current; added = true; return [...base, { role: "assistant", content, timestamp: assistantTimestamp }]; });
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true }); const events = buffer.split("\n\n"); buffer = events.pop() ?? "";
        for (const event of events) {
          const line = event.split("\n").find((item) => item.startsWith("data:")); if (!line) continue;
          const payload = JSON.parse(line.slice(5).trim());
          if (payload.type === "delta") { text += payload.content ?? ""; upsert(text); }
          else if (payload.type === "error") throw new Error(payload.message ?? "AI request failed");
        }
      }
      if (!added) upsert("I couldn't generate a response. Please try again.");
    } catch {
      setMessages((m) => [...m, { role: "assistant", content: "Couldn't reach the AI service. Please try again.", timestamp: assistantTimestamp }]);
    } finally { setSending(false); }
  }

  return (
    <div className="flex h-full min-h-[520px] flex-col lg:border-l lg:border-border">
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <span className="text-xs uppercase tracking-wide text-text-muted">ManiQuant AI</span>
        <span className="flex items-center gap-1.5 rounded-md border border-border bg-bg-raised px-2 py-0.5 text-xs text-text-muted"><span className="h-1.5 w-1.5 rounded-full bg-accent" />Ready</span>
      </div>
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {messages.map((m, i) => <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}><div className={["max-w-[90%] whitespace-pre-line rounded-lg px-4 py-3 text-sm leading-relaxed", m.role === "user" ? "bg-accent-dim text-text border border-accent/20" : "bg-bg-panel text-text border border-border"].join(" ")}><p>{m.content}</p><span className="mt-2 block text-[10px] text-text-faint">{m.role === "user" ? "You" : "ManiQuant AI"} · {m.timestamp}</span></div></div>)}
        {sending && <div className="flex justify-start"><div className="rounded-lg border border-border bg-bg-panel px-4 py-2.5 text-sm text-text-faint">Thinking…</div></div>}
      </div>
      <div className="border-t border-border p-4"><div className="flex items-center gap-2 rounded-lg border border-border bg-bg-panel px-3 py-2"><input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && sendMessage()} placeholder="Tell ManiQuant AI what you want to trade…" className="flex-1 bg-transparent text-sm text-text placeholder:text-text-faint outline-none" /><button onClick={sendMessage} disabled={sending} className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-bg disabled:opacity-40" aria-label="Send message"><ArrowUp size={14} /></button></div></div>
    </div>
  );
}
