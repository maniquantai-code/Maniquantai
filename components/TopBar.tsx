"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown, Menu, Settings, X } from "lucide-react";
import { useStrategies } from "@/context/StrategyContext";
import { supabase } from "@/lib/supabase";

const STATUS_LABELS: Record<string, string> = {
  draft: "Draft", created: "Starting…",
  research_running: "Researching…", research_complete: "Research done",
  research_failed: "Research failed",
  backtesting: "Backtesting…", backtest_complete: "Backtest done",
  backtest_failed: "Backtest failed",
  indicator_ready: "Checking indicators…", risk_ready: "Risk cleared",
  awaiting_live_approval: "Awaiting approval",
  live_approved: "Live", live_running: "Live ●",
  live_blocked: "Live off",
  pending_backtest: "Backtesting…", paper_trade: "Paper trading",
  approved_for_live: "Approved", live: "Live", paused: "Paused",
};

export function TopBar({ tier = "PRO" }: { tier?: string }) {
  const { strategies, selectedId, selectStrategy } = useStrategies();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [avatarInitial, setAvatarInitial] = useState("U");

  useEffect(() => {
    let mounted = true;
    supabase.auth.getUser().then(({ data }) => {
      const initial = data.user?.email?.trim()?.charAt(0).toUpperCase();
      if (mounted && initial) setAvatarInitial(initial);
    });
    return () => { mounted = false; };
  }, []);

  const selected = strategies.find(s => s.strategy_id === selectedId);
  const isLive = selected?.spec?.live_approved || selected?.status === "live_approved";

  return (
    <>
      <header className="flex items-center justify-between border-b border-border px-4 py-3 sm:px-6">
        {/* Left — logo */}
        <div className="flex items-center gap-2 sm:gap-3">
          <button
            className="rounded-md p-1.5 text-text-muted hover:bg-bg-raised lg:hidden"
            onClick={() => setMobileMenuOpen(true)}
            aria-label="Open menu"
          >
            <Menu size={20} />
          </button>
          <Link href="/dashboard" className="flex items-center gap-2 sm:gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-dim text-accent">
              <span className="text-sm font-bold">M</span>
            </div>
            <span className="hidden font-semibold tracking-tight sm:inline">ManiQuantAI</span>
          </Link>
        </div>

        {/* Centre — strategy selector */}
        <div className="relative hidden sm:block">
          <button
            onClick={() => setDropdownOpen(v => !v)}
            className="flex items-center gap-2 rounded-lg border border-border bg-bg-panel px-3 py-1.5 text-sm text-text hover:bg-bg-raised transition-colors max-w-[240px]"
          >
            <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${isLive ? "bg-green-400 animate-pulse" : "bg-accent"}`} />
            <span className="truncate">{selected?.name ?? "Select a strategy"}</span>
            <ChevronDown size={14} className="flex-shrink-0 text-text-muted" />
          </button>

          {dropdownOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setDropdownOpen(false)} />
              <div className="absolute left-0 z-20 mt-2 w-72 rounded-lg border border-border bg-bg-panel p-1.5 shadow-xl">
                {strategies.length === 0 && (
                  <p className="px-3 py-4 text-center text-xs text-text-muted">
                    No strategies yet — tell ManiQuantAI what you want to trade in the chat.
                  </p>
                )}
                {strategies.map(s => {
                  const live = s.spec?.live_approved || s.status === "live_approved";
                  return (
                    <button
                      key={s.strategy_id}
                      onClick={() => { selectStrategy(s.strategy_id); setDropdownOpen(false); }}
                      className={`flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm hover:bg-bg-raised ${s.strategy_id === selectedId ? "bg-accent-dim" : ""}`}
                    >
                      <div className="min-w-0">
                        <div className="truncate text-text">{s.name}</div>
                        <div className="text-xs text-text-faint">{STATUS_LABELS[s.status] ?? s.status}</div>
                      </div>
                      {live && <span className="ml-2 h-1.5 w-1.5 shrink-0 rounded-full bg-green-400 animate-pulse" />}
                    </button>
                  );
                })}
                <div className="my-1 border-t border-border pt-2 px-3 pb-1">
                  <p className="text-[11px] text-text-faint">
                    💬 Type your strategy in the chat to create a new one
                  </p>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Right — tier badge + avatar */}
        <div className="flex items-center gap-2 sm:gap-3">
          <span className="rounded-md border border-accent/30 bg-accent-dim px-2 py-0.5 text-xs font-medium text-accent">
            {tier}
          </span>
          <Link
            href="/settings"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-bg-raised text-xs font-medium text-text-muted hover:bg-border transition-colors"
            aria-label="Settings"
          >
            {avatarInitial}
          </Link>
        </div>
      </header>

      {/* Mobile menu */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileMenuOpen(false)} />
          <div className="absolute left-0 top-0 h-full w-72 bg-bg-panel p-4">
            <div className="mb-4 flex items-center justify-between">
              <span className="text-xs uppercase tracking-wide text-text-muted">Strategies</span>
              <button onClick={() => setMobileMenuOpen(false)} className="text-text-muted">
                <X size={18} />
              </button>
            </div>
            <div className="space-y-1">
              {strategies.length === 0 && (
                <p className="px-2 py-3 text-xs text-text-muted">
                  No strategies yet — describe what you want to trade in the chat.
                </p>
              )}
              {strategies.map(s => (
                <button
                  key={s.strategy_id}
                  onClick={() => { selectStrategy(s.strategy_id); setMobileMenuOpen(false); }}
                  className={`flex w-full flex-col items-start rounded-md px-3 py-2 text-left text-sm hover:bg-bg-raised ${s.strategy_id === selectedId ? "bg-accent-dim" : ""}`}
                >
                  <span className="text-text">{s.name}</span>
                  <span className="text-xs text-text-faint">{STATUS_LABELS[s.status] ?? s.status}</span>
                </button>
              ))}
            </div>
            <div className="my-3 h-px bg-border" />
            <Link
              href="/settings"
              onClick={() => setMobileMenuOpen(false)}
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-text-muted hover:bg-bg-raised"
            >
              <Settings size={14} /> Settings
            </Link>
          </div>
        </div>
      )}
    </>
  );
}
