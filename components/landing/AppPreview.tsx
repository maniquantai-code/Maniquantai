"use client";
import { PipelineStepper, Stage } from "@/components/PipelineStepper";
import { MetricsPanel, StrategyMetrics } from "@/components/MetricsPanel";
import { HeightenedMonitoringBadge } from "@/components/HeightenedMonitoringBadge";

const previewStages: Stage[] = [
  { label: "Research", status: "complete" },
  { label: "Backtest", status: "complete" },
  { label: "Paper", status: "current" },
  { label: "Approval", status: "upcoming" },
  { label: "Live", status: "upcoming" },
];

const previewMetrics: StrategyMetrics = {
  status: "PASSED",
  winRate: 68,
  tradeCount: 847,
  winLossRatio: 2.1,
  sharpe: 1.74,
  maxDrawdown: -5.8,
};

export function AppPreview() {
  return (
    <div className="relative mx-auto w-full max-w-3xl">
      <div className="overflow-hidden rounded-xl border border-border bg-bg-panel shadow-2xl shadow-black/40">
        <div className="flex items-center gap-1.5 border-b border-border px-4 py-2.5">
          <span className="h-2.5 w-2.5 rounded-full bg-border" />
          <span className="h-2.5 w-2.5 rounded-full bg-border" />
          <span className="h-2.5 w-2.5 rounded-full bg-border" />
          <span className="ml-3 rounded-md bg-bg px-3 py-0.5 text-[11px] text-text-faint">
            app.maniquant.ai/dashboard
          </span>
        </div>

        <div className="pointer-events-none space-y-4 p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-text">EUR/USD Mean Reversion</h3>
            <HeightenedMonitoringBadge day={4} totalDays={14} />
          </div>
          <PipelineStepper stages={previewStages} />
          <MetricsPanel metrics={previewMetrics} />
        </div>
      </div>

      <div
        aria-hidden
        className="pointer-events-none absolute -inset-8 -z-10 rounded-full bg-accent/10 blur-3xl"
      />
    </div>
  );
}
