"use client";
import { useState } from "react";
import { TopBar } from "@/components/TopBar";
import { PipelineStepper, Stage } from "@/components/PipelineStepper";
import { MetricsPanel, StrategyMetrics } from "@/components/MetricsPanel";
import { DrawdownChart, DrawdownPoint } from "@/components/DrawdownChart";
import { HeightenedMonitoringBadge } from "@/components/HeightenedMonitoringBadge";
import { ChatPanel, ChatMessage } from "@/components/ChatPanel";
import { useStrategies } from "@/context/StrategyContext";
import { MessageSquare, LayoutDashboard } from "lucide-react";

const stages: Stage[] = [
  { label: "Research", status: "complete" },
  { label: "Backtest", status: "complete" },
  { label: "Paper", status: "current" },
  { label: "Approval", status: "upcoming" },
  { label: "Live", status: "upcoming" },
];

const metrics: StrategyMetrics = {
  status: "PASSED",
  winRate: 68,
  tradeCount: 847,
  winLossRatio: 2.1,
  sharpe: 1.74,
  maxDrawdown: -5.8,
};

const drawdownData: DrawdownPoint[] = [
  { month: "Jan", drawdown: 0 }, { month: "Feb", drawdown: -1.2 },
  { month: "Mar", drawdown: -3.1 }, { month: "Apr", drawdown: -4.8 },
  { month: "May", drawdown: -3.9 }, { month: "Jun", drawdown: -2.4 },
  { month: "Jul", drawdown: -1.8 }, { month: "Aug", drawdown: -3.2 },
  { month: "Sep", drawdown: -5.8 }, { month: "Oct", drawdown: -4.1 },
  { month: "Nov", drawdown: -2.6 }, { month: "Dec", drawdown: -1.5 },
];

const initialMessages: ChatMessage[] = [
  {
    role: "user",
    content:
      "Trade EUR/USD when the 4-hour price returns to the 20-period mean after a 1.5 ATR deviation. Exit at mean or after 48 hours.",
    timestamp: "14:28",
  },
  {
    role: "assistant",
    content:
      "Got it. I'm running this against 36 months of EUR/USD 4H data — that gives us enough samples across rate cycles. Expect an initial report in a few minutes.",
    timestamp: "14:29",
  },
  { role: "user", content: "How does the win rate look so far?", timestamp: "14:43" },
  {
    role: "assistant",
    content:
      "Strong — 68% win rate across 847 trades, with an average win about 2.1x the average loss, so the risk/reward backs up the win rate rather than just looking good on its own. Max simulated drawdown was 5.8%. This strategy is currently in paper trading — want me to walk through what's happening day to day?",
    timestamp: "14:44",
  },
];

export default function DashboardPage() {
  const { strategies, selectedId } = useStrategies();
  const [mobileTab, setMobileTab] = useState<"overview" | "chat">("overview");

  const selected = strategies.find((s) => s.strategy_id === selectedId) ?? strategies[0];

  if (!selected) {
    return (
      <div className="flex h-screen flex-col bg-bg">
        <TopBar tier="PRO" />
        <div className="flex flex-1 items-center justify-center text-text-muted">
          No strategies yet — create one to get started.
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-bg">
      <TopBar tier="PRO" />

      <div className="flex flex-1 overflow-hidden">
        <main
          className={`flex-1 space-y-5 overflow-y-auto p-4 sm:p-6 ${
            mobileTab === "chat" ? "hidden lg:block" : "block"
          }`}
        >
          <div>
            <div className="mb-1 flex flex-wrap items-center gap-2 sm:gap-3">
              <h1 className="text-lg font-semibold sm:text-xl">{selected.name}</h1>
              {selected.heightened_monitoring_day && selected.heightened_monitoring_total && (
                <HeightenedMonitoringBadge
                  day={selected.heightened_monitoring_day}
                  totalDays={selected.heightened_monitoring_total}
                />
              )}
            </div>
            <p className="text-sm text-text-muted">
              Paper trading
              {selected.fast_track ? " · Fast Track active" : ""} · Automated strategy pending
              live approval
            </p>
          </div>

          <PipelineStepper stages={stages} />
          <MetricsPanel metrics={metrics} />
          <DrawdownChart data={drawdownData} />
        </main>

        <aside
          className={`w-full flex-shrink-0 lg:w-[380px] ${
            mobileTab === "overview" ? "hidden lg:block" : "block"
          }`}
        >
          <ChatPanel strategyId={selected.strategy_id} initialMessages={initialMessages} />
        </aside>
      </div>

      <nav className="flex border-t border-border lg:hidden">
        <button
          onClick={() => setMobileTab("overview")}
          className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs ${
            mobileTab === "overview" ? "text-accent" : "text-text-faint"
          }`}
        >
          <LayoutDashboard size={18} />
          Overview
        </button>
        <button
          onClick={() => setMobileTab("chat")}
          className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs ${
            mobileTab === "chat" ? "text-accent" : "text-text-faint"
          }`}
        >
          <MessageSquare size={18} />
          Chat
        </button>
      </nav>
    </div>
  );
}
