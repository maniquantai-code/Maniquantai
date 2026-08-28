"use client";
import { useState } from "react";
import { X, Zap, Loader2 } from "lucide-react";
import { useStrategies } from "@/context/StrategyContext";

interface Props {
  onClose: () => void;
}

const EXAMPLES = [
  "BTC/USD 15m · RSI 14 below 30 + lower Bollinger Band 20 · exit RSI above 55 · 1% risk · ATR 1.5x stop · 2R target",
  "ETH/USD 1h · EMA 9 crosses above EMA 21 · ADX > 20 · 1% risk · ATR 1.5x stop · 3R target",
  "SOL/USD breakout above 20-bar resistance with 1.5x volume · 1.5% risk · ATR stop",
  "XAU/USD 5m scalping · EMA 3 crosses EMA 8 · RSI 7 between 40–65 · 0.5% risk",
];

export function NewStrategyModal({ onClose }: Props) {
  const { createStrategy, creating } = useStrategies();
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  async function handleCreate() {
    const trimmed = text.trim();
    if (!trimmed) { setError("Describe your strategy first."); return; }
    if (trimmed.length < 15) { setError("Add more detail — include symbol, timeframe, and entry condition."); return; }
    setError("");
    try {
      await createStrategy(trimmed);
      onClose();
    } catch (e: any) {
      setError(
        e?.message?.includes("sign in") ? "Session expired — please refresh the page." :
        e?.message?.includes("authorized") ? "Account not authorized. Please sign out and back in." :
        e?.message?.includes("profile") ? "Profile not ready. Sign out, sign in, then retry." :
        "Couldn't save the strategy. Check your connection and try again."
      );
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-lg rounded-2xl border border-border bg-bg-panel shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-2">
            <Zap size={18} className="text-accent" />
            <h2 className="text-base font-semibold">New strategy</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-text-muted hover:bg-bg-raised hover:text-text transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4">
          <p className="text-sm text-text-muted leading-6">
            Describe your trading strategy in plain English. The agent team compiles it and starts Research immediately.
          </p>

          <textarea
            autoFocus
            value={text}
            onChange={e => { setText(e.target.value); setError(""); }}
            onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleCreate(); }}
            placeholder="e.g. BTC/USD 15m · RSI 14 below 30 + lower Bollinger Band · exit RSI above 55 · 1% risk · ATR 1.5x stop · 2R target"
            rows={4}
            className="w-full resize-none rounded-xl border border-border bg-bg-raised px-4 py-3 text-sm text-text placeholder:text-text-faint focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/30 leading-6 transition-colors"
          />

          {/* Examples */}
          <div>
            <p className="mb-2 text-[11px] uppercase tracking-wide text-text-faint">Quick examples</p>
            <div className="space-y-1.5">
              {EXAMPLES.map(ex => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => { setText(ex); setError(""); }}
                  className="block w-full rounded-lg border border-border bg-bg-raised px-3 py-2 text-left text-xs text-text-muted hover:border-accent/40 hover:text-text transition-colors"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <p className="rounded-lg border border-red-800/40 bg-red-950/20 px-3 py-2 text-xs text-red-300">
              {error}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border px-6 py-4">
          <p className="text-[11px] text-text-faint">
            Research → Backtest → Indicators → Risk → Approval → Live
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={creating}
              className="rounded-lg border border-border px-4 py-2 text-sm text-text-muted hover:bg-bg-raised transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreate}
              disabled={creating || !text.trim()}
              className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              {creating
                ? <><Loader2 size={14} className="animate-spin" /> Creating…</>
                : <><Zap size={14} /> Start pipeline</>}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
