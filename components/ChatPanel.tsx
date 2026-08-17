"use client";
import { useState, useRef, useEffect } from "react";
import { ArrowUp } from "lucide-react";
import { getAccessToken } from "@/lib/supabase";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

export function ChatPanel({
  strategyId,
  initialMessages,
}: {
  strategyId: string;
  initialMessages: ChatMessage[];
}) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function sendMessage() {
    if (!input.trim() || sending) return;
    const userMsg: ChatMessage = {
      role: "user",
      content: input,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setSending(true);

    try {
      const token = await getAccessToken();
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ strategy_id: strategyId, message: userMsg.content }),
      });
      const data = await res.json();
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: data.reply ?? "Sorry, something went wrong on my end.",
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: "Couldn't reach the backend. Is it running on port 8000?",
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full flex-col lg:border-l lg:border-border">
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <span className="text-xs uppercase tracking-wide text-text-muted">Strategy chat</span>
        <span className="flex items-center gap-1.5 rounded-md border border-border bg-bg-raised px-2 py-0.5 text-xs text-text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          Vela AI
        </span>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={[
                "max-w-[85%] rounded-lg px-4 py-2.5 text-sm leading-relaxed",
                m.role === "user"
                  ? "bg-accent-dim text-text border border-accent/20"
                  : "bg-bg-panel text-text border border-border",
              ].join(" ")}
            >
              <p>{m.content}</p>
              <span className="mt-1 block text-[10px] text-text-faint">
                {m.role === "user" ? "You" : "ManiQuant AI"} · {m.timestamp}
              </span>
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="rounded-lg border border-border bg-bg-panel px-4 py-2.5 text-sm text-text-faint">
              Thinking…
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-border p-4">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-bg-panel px-3 py-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="Describe a strategy or ask a question…"
            className="flex-1 bg-transparent text-sm text-text placeholder:text-text-faint outline-none"
          />
          <button
            onClick={sendMessage}
            disabled={sending}
            className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-bg disabled:opacity-40"
            aria-label="Send message"
          >
            <ArrowUp size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
