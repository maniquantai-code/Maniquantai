"use client";
import { useState } from "react";
import { X } from "lucide-react";
import Link from "next/link";
import { useStrategies } from "@/context/StrategyContext";

export function NewStrategyModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { createStrategy, creating, createError } = useStrategies();
  const [text, setText] = useState("");

  if (!open) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    await createStrategy(text);
    if (!createError) {
      setText("");
      onClose();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-lg rounded-lg border border-border bg-bg-panel p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">New strategy</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Describe your strategy in plain English — e.g. 'Buy BTC when RSI drops below 30 and price is above the 200 EMA. Stop loss 2%, take profit 5%.'"
            rows={5}
            className="w-full resize-none rounded-lg border border-border bg-bg px-3 py-2.5 text-sm text-text placeholder:text-text-faint outline-none focus:border-accent"
          />

          {createError && (
            <div className="mt-2 rounded-lg border border-danger/30 bg-danger-dim p-3">
              <p className="text-sm text-danger">{createError}</p>
              {createError.toLowerCase().includes("credit") && (
                <Link
                  href="/settings"
                  className="mt-1.5 inline-block text-xs font-medium text-accent hover:underline"
                >
                  View plans & upgrade →
                </Link>
              )}
            </div>
          )}

          <p className="mt-2 text-xs text-text-faint">
            This will go through Research → Backtest → Paper Trading before any real capital is
            at risk. Every strategy needs a stop-loss and position sizing.
          </p>

          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border px-4 py-2 text-sm text-text-muted hover:bg-bg-raised"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={creating || !text.trim()}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg disabled:opacity-40"
            >
              {creating ? "Analyzing…" : "Start research"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
