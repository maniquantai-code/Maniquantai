"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, ImagePlus, X } from "lucide-react";
import { getAccessToken, supabase } from "@/lib/supabase";
import { useStrategies } from "@/context/StrategyContext";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  image?: string;
}

type Gate = "research" | "backtest" | "approval" | "paper" | "live" | null;

const now = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function gateFromPending(v?: string | null): Gate {
  if (v === "research_start") return "research";
  if (v === "backtest" || v === "backtest_review") return "backtest";
  if (v === "approval") return "approval";
  if (v === "paper_launch") return "paper";
  if (v === "live_approval") return "live";
  return null;
}

const WELCOME = `👋 **Welcome to ManiQuantAI**

Tell me what you want to trade and I'll build, test, and run it for you through a 6-agent team.

**Try one of these:**
• BTC/USD 15m · RSI 14 below 30 + Bollinger lower band · exit RSI above 55 · 1% risk · ATR 1.5x stop · 2R target
• ETH/USD 1h · EMA 9 crosses EMA 21 · ADX > 20 · 1% risk · 3R target
• SOL/USD breakout above 20-bar resistance · 1.5x volume · 1.5% risk
• XAU/USD 5m scalping · EMA 3/8 · RSI 7 between 40–65 · 0.5% risk

Just type your strategy and I'll handle everything — Research, Backtest, Indicators, Risk, and Live execution through MetaTrader 5.`;

export function ChatPanel({
  strategyId,
  initialMessages,
  onboarding = false,
}: {
  strategyId?: string;
  initialMessages?: ChatMessage[];
  onboarding?: boolean;
}) {
  const { createStrategy, creating, strategies, selectedId } = useStrategies();
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages ?? []);
  const [input, setInput] = useState("");
  const [image, setImage] = useState<string>();
  const [sending, setSending] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(!!strategyId);
  const [gate, setGate] = useState<Gate>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const activeId = strategyId || selectedId;

  const persist = async (role: "user" | "assistant", content: string) => {
    if (!activeId || !content.trim()) return;
    try { await supabase.from("chat_messages").insert({ strategy_id: activeId, role, content: content.trim() }); } catch { /* non-critical */ }
  };

  const addMsg = (role: "user" | "assistant", content: string, img?: string) => {
    setMessages(m => [...m, { role, content, timestamp: now(), image: img }]);
    if (role === "assistant") void persist("assistant", content);
  };

  // Load chat history
  useEffect(() => {
    let mounted = true;
    (async () => {
      if (!activeId) {
        setHistoryLoading(false);
        if (!messages.length) addMsg("assistant", WELCOME);
        return;
      }
      setHistoryLoading(true);
      const { data, error } = await supabase
        .from("chat_messages").select("role,content,created_at")
        .eq("strategy_id", activeId).order("created_at", { ascending: true }).limit(500);
      if (!mounted) return;
      if (!error && data?.length) {
        setMessages(data.map((m: any) => ({
          role: m.role, content: m.content,
          timestamp: new Date(m.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        })));
      } else if (!error && initialMessages?.length) {
        setMessages(initialMessages);
      } else if (!error && !data?.length) {
        // New strategy — show welcome
        addMsg("assistant", WELCOME);
      }
      // Restore gate
      try {
        const token = await getAccessToken();
        const r = await fetch(`/api/pipeline/status/${activeId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (r.ok) { const p = await r.json(); const g = gateFromPending(p.pending_confirmation); if (g) setGate(g); }
      } catch {}
      if (mounted) setHistoryLoading(false);
    })();
    return () => { mounted = false; };
  }, [activeId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // Image handling
  const acceptImage = (file?: File | null) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => { if (e.target?.result) setImage(e.target.result as string); };
    reader.readAsDataURL(file);
  };
  const onPaste = (e: React.ClipboardEvent) => {
    const item = Array.from(e.clipboardData.items).find(i => i.type.startsWith("image/"));
    if (item) { e.preventDefault(); acceptImage(item.getAsFile()); }
  };

  // Backend chat call
  async function backendMessage(content: string, attached?: string, showUser = true) {
    if (!activeId) throw new Error("no_strategy");
    const token = await getAccessToken();
    if (showUser) { addMsg("user", content, attached); await persist("user", content); }
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ strategy_id: activeId, message: content, image: attached || null }),
    });
    if (!res.ok) {
      const raw = await res.text();
      let detail = raw;
      try { const j = JSON.parse(raw); detail = j.detail || j.content || j.message || raw; } catch {}
      throw new Error(String(detail).slice(0, 300));
    }
    if (!res.body) throw new Error("No response from AI service.");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    let raw = ""; let buffer = ""; let text = ""; let final = ""; let added = false;
    const ts = now();
    const upsert = (next: string) => {
      final = next;
      setMessages(m => { const base = added ? m.slice(0, -1) : m; added = true; return [...base, { role: "assistant", content: next, timestamp: ts }]; });
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      if (ct.includes("application/json")) { raw += chunk; }
      else {
        buffer += chunk;
        const events = buffer.split("\n\n"); buffer = events.pop() ?? "";
        for (const event of events) {
          const line = event.split("\n").find(x => x.startsWith("data:"));
          if (!line) continue;
          let p: any; try { p = JSON.parse(line.slice(5).trim()); } catch { continue; }
          if (p.type === "delta") { text += p.content ?? ""; if (text) upsert(text); }
          else if (p.type === "error") throw new Error(p.message ?? "AI service failed");
        }
      }
    }

    if (ct.includes("application/json")) {
      let p: any; try { p = JSON.parse(raw); } catch { throw new Error("Invalid response from AI service."); }
      final = p.content || p.message || "Done.";
      setMessages(m => [...m, { role: "assistant", content: final, timestamp: now() }]);
      await persist("assistant", final);
      // Set gate from action
      const a = p.action;
      if (a === "confirm_research") setGate("research");
      else if (a === "confirm_backtest" || a === "backtest_ready") setGate("backtest");
      else if (a === "approval") setGate("approval");
      else if (a === "paper_ready") setGate("paper");
      else if (["live_ready","request_live_approval","live_approval","risk_ready"].includes(a)) setGate("live");
      else if (["paper_started","live_running","research_started"].includes(a)) setGate(null);
      return final;
    }
    if (!final) upsert("Request complete. Check the dashboard for agent progress.");
    if (final) await persist("assistant", final);
    return final;
  }

  // Gate buttons
  async function submitGate(choice: "yes" | "no") {
    if (!activeId || !gate || sending) return;
    const current = gate;
    setSending(true);
    addMsg("user", choice === "yes" ? "Yes" : "No");
    await persist("user", choice === "yes" ? "Yes" : "No");
    try {
      if (choice === "no") {
        setGate(null);
        addMsg("assistant", current === "live"
          ? "Live trading stays off. No order submitted. Type 'start live trading' whenever you're ready."
          : "Paused. Type 'yes' whenever you want to continue.");
        return;
      }
      setGate(null);
      addMsg("assistant", current === "live" ? "Approving live trading…" : "Processing…");
      await backendMessage(current === "live" ? "yes" : "yes", undefined, false);
    } catch (e) {
      setGate(current);
      addMsg("assistant", `Something went wrong — no trading action was taken. Please try again.`);
    } finally { setSending(false); }
  }

  // Main send — handles both new strategy creation AND chat
  async function sendMessage() {
    const content = input.trim();
    if ((!content && !image) || sending) return;
    setInput("");
    const attached = image; setImage(undefined);

    // No strategy yet — create one from this message
    if (!activeId && content && content.length >= 15) {
      setSending(true);
      addMsg("user", content);
      addMsg("assistant", "⏳ Got it — compiling your strategy and starting Research…");
      try {
        await createStrategy(content);
        // StrategyContext will select the new strategy; chat will reload via useEffect
      } catch (e: any) {
        setMessages(m => m.slice(0, -1)); // remove the "compiling" message
        addMsg("assistant",
          e?.message?.includes("sign in") ? "Session expired — please refresh the page." :
          "Couldn't create the strategy. Check your connection and try again."
        );
      } finally { setSending(false); }
      return;
    }

    if (!activeId) {
      addMsg("assistant",
        "Describe your trading strategy and I'll create it for you.\n\n" +
        "**Example:** BTC/USD 15m · RSI 14 below 30 + lower Bollinger Band · exit RSI above 55 · 1% risk · ATR 1.5x stop · 2R target"
      );
      return;
    }

    setSending(true);
    try { await backendMessage(content || "Analyse this chart.", attached, true); }
    catch (e) { addMsg("assistant", e instanceof Error && e.message === "no_strategy"
      ? "Select or describe a strategy first."
      : `Something went wrong — no trading action was taken. Please try again.`);
    } finally { setSending(false); }
  }

  const gatePrompt =
    gate === "research"  ? "Start Research Agent?" :
    gate === "backtest"  ? "Run the deterministic backtest?" :
    gate === "approval"  ? "Approve strategy for paper trading?" :
    gate === "paper"     ? "Start paper trading?" :
    gate === "live"      ? "Approve live trading?" : "";

  const isOnline = true;

  return (
    <div className="flex h-full min-h-[520px] flex-col lg:border-l lg:border-border">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <span className="text-xs uppercase tracking-wide text-text-muted">ManiQuant AI</span>
        <span className="flex items-center gap-1.5 rounded-md border border-border bg-bg-raised px-2 py-0.5 text-xs text-text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" /> Ready
        </span>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        onPaste={onPaste}
        onDragOver={e => e.preventDefault()}
        onDrop={e => { e.preventDefault(); acceptImage(e.dataTransfer.files?.[0]); }}
        className="flex-1 space-y-4 overflow-y-auto px-5 py-4"
      >
        {historyLoading ? (
          <div className="py-6 text-center text-xs text-text-faint">Loading…</div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div className={[
                "max-w-[92%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
                m.role === "user"
                  ? "bg-accent-dim text-text border border-accent/20 rounded-br-sm"
                  : "bg-bg-panel text-text border border-border rounded-bl-sm",
              ].join(" ")}>
                {m.image && (
                  <img src={m.image} alt="Chart" className="mb-3 max-h-72 max-w-full rounded-lg border border-border object-contain" />
                )}
                <p className="whitespace-pre-line">{m.content}</p>
                <span className="mt-1.5 block text-[10px] text-text-faint">
                  {m.role === "user" ? "You" : "ManiQuant AI"} · {m.timestamp}
                </span>
              </div>
            </div>
          ))
        )}

        {/* Gate buttons */}
        {gate && (
          <div className="rounded-xl border border-accent/20 bg-accent/5 p-4">
            <p className="mb-3 text-sm font-medium text-text">{gatePrompt}</p>
            <div className="flex gap-2">
              <button onClick={() => void submitGate("yes")} disabled={sending}
                className="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-bg hover:bg-accent/90 disabled:opacity-50 transition-colors">
                {sending ? "Working…" : "Yes"}
              </button>
              <button onClick={() => void submitGate("no")} disabled={sending}
                className="rounded-lg border border-border bg-bg-raised px-5 py-2 text-sm text-text hover:bg-border disabled:opacity-50 transition-colors">
                No
              </button>
            </div>
          </div>
        )}

        {sending && !gate && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-sm border border-border bg-bg-panel px-4 py-3 text-sm text-text-faint">
              <span className="inline-flex gap-1">
                <span className="animate-bounce" style={{ animationDelay: "0ms" }}>·</span>
                <span className="animate-bounce" style={{ animationDelay: "150ms" }}>·</span>
                <span className="animate-bounce" style={{ animationDelay: "300ms" }}>·</span>
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-border p-4">
        {image && (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-border bg-bg-raised p-2">
            <img src={image} alt="Preview" className="h-14 w-20 rounded object-cover" />
            <span className="flex-1 text-xs text-text-muted">Chart attached</span>
            <button type="button" onClick={() => setImage(undefined)} className="rounded p-1 text-text-muted hover:text-text">
              <X size={14} />
            </button>
          </div>
        )}
        <div className="flex items-center gap-2 rounded-xl border border-border bg-bg-panel px-3 py-2 focus-within:border-accent/50 transition-colors">
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
            onChange={e => acceptImage(e.target.files?.[0])} />
          <button type="button" onClick={() => fileRef.current?.click()} disabled={sending}
            className="flex h-7 w-7 items-center justify-center rounded-md text-text-muted hover:bg-bg-raised disabled:opacity-40 transition-colors"
            aria-label="Attach chart">
            <ImagePlus size={16} />
          </button>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void sendMessage(); } }}
            placeholder={activeId ? "Message ManiQuant AI…" : "Describe your trading strategy to get started…"}
            className="flex-1 bg-transparent text-sm text-text placeholder:text-text-faint outline-none"
          />
          <button onClick={() => void sendMessage()}
            disabled={sending || creating || (!input.trim() && !image)}
            className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-bg hover:bg-accent/90 disabled:opacity-40 transition-colors"
            aria-label="Send">
            <ArrowUp size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
