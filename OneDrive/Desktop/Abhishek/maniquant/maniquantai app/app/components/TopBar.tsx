"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown, Menu, Plus, Settings, X } from "lucide-react";
import { useStrategies } from "@/context/StrategyContext";
import { NewStrategyModal } from "./NewStrategyModal";
import { supabase } from "@/lib/supabase";

const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  pending_backtest: "Backtesting…",
  backtest_failed: "Backtest failed",
  pending_paper_trade: "Ready for paper trading",
  paper_trade: "Paper trading",
  pending_human_approval: "Awaiting approval",
  approved_for_live: "Approved",
  live: "Live",
  paused: "Paused",
  disabled: "Disabled",
};

export function TopBar({ tier = "PRO" }: { tier?: string }) {
  const { strategies, selectedId, selectStrategy } = useStrategies();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [newStrategyOpen, setNewStrategyOpen] = useState(false);
  const [avatarInitial, setAvatarInitial] = useState("U");

  useEffect(() => {
    let mounted = true;
    supabase.auth.getUser().then(({ data }) => {
      const initial = data.user?.email?.trim()?.charAt(0).toUpperCase();
      if (mounted && initial) setAvatarInitial(initial);
    });
    return () => {
      mounted = false;
    };
  }, []);

  const selected = strategies.find((s) => s.strategy_id === selectedId);

  return (
    <>
      <header className="flex items-center justify-between border-b border-border px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2 sm:gap-3">
          {/* Mobile hamburger */}
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

        {/* Strategy selector -- hidden on very small screens, shown from sm up */}
        <div className="relative hidden sm:block">
          <button
            onClick={() => setDropdownOpen((v) => !v)}
            className="flex items-center gap-2 rounded-lg border border-border bg-bg-panel px-3 py-1.5 text-sm text-text hover:bg-bg-raised transition-colors max-w-[220px] md:max-w-none"
          >
            <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-accent" />
            <span className="truncate">{selected?.name ?? "Select a strategy"}</span>
            <ChevronDown size={14} className="flex-shrink-0 text-text-muted" />
          </button>

          {dropdownOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setDropdownOpen(false)} />
              <div className="absolute left-0 z-20 mt-2 w-72 rounded-lg border border-border bg-bg-panel p-1.5 shadow-xl">
                {strategies.map((s) => (
                  <button
                    key={s.strategy_id}
                    onClick={() => {
                      selectStrategy(s.strategy_id);
                      setDropdownOpen(false);
                    }}
                    className={`flex w-full flex-col items-start rounded-md px-3 py-2 text-left text-sm hover:bg-bg-raised ${
                      s.strategy_id === selectedId ? "bg-accent-dim" : ""
                    }`}
                  >
                    <span className="text-text">{s.name}</span>
                    <span className="text-xs text-text-faint">
                      {STATUS_LABELS[s.status] ?? s.status}
                    </span>
                  </button>
                ))}
                <div className="my-1 h-px bg-border" />
                <button
                  onClick={() => {
                    setDropdownOpen(false);
                    setNewStrategyOpen(true);
                  }}
                  className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-accent hover:bg-bg-raised"
                >
                  <Plus size={14} /> New strategy
                </button>
              </div>
            </>
          )}
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <button
            onClick={() => setNewStrategyOpen(true)}
            className="hidden items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-bg sm:flex"
          >
            <Plus size={14} /> New
          </button>
          <span className="rounded-md border border-accent/30 bg-accent-dim px-2 py-0.5 text-xs font-medium text-accent">
            {tier}
          </span>
          <Link
            href="/settings"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-bg-raised text-xs font-medium text-text-muted hover:bg-border"
            aria-label="Settings"
          >
            {avatarInitial}
          </Link>
        </div>
      </header>

      {/* Mobile slide-over menu */}
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
              {strategies.map((s) => (
                <button
                  key={s.strategy_id}
                  onClick={() => {
                    selectStrategy(s.strategy_id);
                    setMobileMenuOpen(false);
                  }}
                  className={`flex w-full flex-col items-start rounded-md px-3 py-2 text-left text-sm hover:bg-bg-raised ${
                    s.strategy_id === selectedId ? "bg-accent-dim" : ""
                  }`}
                >
                  <span className="text-text">{s.name}</span>
                  <span className="text-xs text-text-faint">
                    {STATUS_LABELS[s.status] ?? s.status}
                  </span>
                </button>
              ))}
            </div>
            <div className="my-3 h-px bg-border" />
            <button
              onClick={() => {
                setMobileMenuOpen(false);
                setNewStrategyOpen(true);
              }}
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-accent hover:bg-bg-raised"
            >
              <Plus size={14} /> New strategy
            </button>
            <Link
              href="/settings"
              onClick={() => setMobileMenuOpen(false)}
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-text-muted hover:bg-bg-raised"
            >
              <Settings size={14} /> Settings & billing
            </Link>
          </div>
        </div>
      )}

      <NewStrategyModal open={newStrategyOpen} onClose={() => setNewStrategyOpen(false)} />
    </>
  );
}
