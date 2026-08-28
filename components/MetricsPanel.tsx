"use client";

export interface StrategyMetrics {
  status: "PASSED" | "FAILED" | "PENDING";
  winRate: number;
  tradeCount: number;
  winLossRatio: number;
  sharpe: number;
  maxDrawdown: number;
}

export function MetricsPanel({ metrics }: { metrics: StrategyMetrics }) {
  const statusColor =
    metrics.status === "PASSED"
      ? "text-accent border-accent/30 bg-accent-dim"
      : metrics.status === "FAILED"
      ? "text-danger border-danger/30 bg-danger-dim"
      : "text-warn border-warn/30 bg-warn-dim";

  return (
    <div className="rounded-lg border border-border bg-bg-panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-text-muted">
          Strategy metrics — backtest
        </span>
        <span className={`rounded-md border px-2 py-0.5 text-xs font-medium ${statusColor}`}>
          {metrics.status}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:gap-6 md:grid-cols-4">
        <Metric
          label="Win rate"
          value={`${metrics.winRate}%`}
          sublabel={`${metrics.tradeCount} trades`}
        />
        <Metric
          label="Avg win / loss"
          value={`${metrics.winLossRatio}x`}
          sublabel="ratio (positive)"
          valueClass="text-accent"
        />
        <Metric label="Sharpe" value={metrics.sharpe.toFixed(2)} sublabel="annualized" />
        <Metric
          label="Max drawdown"
          value={`${metrics.maxDrawdown}%`}
          sublabel="simulated"
        />
      </div>

      {/* Win rate is intentionally never shown without avg win/loss beside it --
          this mirrors backtest-interpreter's rule: never report win rate alone. */}
    </div>
  );
}

function Metric({
  label,
  value,
  sublabel,
  valueClass = "text-text",
}: {
  label: string;
  value: string;
  sublabel: string;
  valueClass?: string;
}) {
  return (
    <div>
      <div className="mb-1 text-xs text-text-muted">{label}</div>
      <div className={`text-2xl font-semibold ${valueClass}`}>{value}</div>
      <div className="text-xs text-text-faint">{sublabel}</div>
    </div>
  );
}
