"use client";

import { useState } from "react";
import { TopBar } from "@/components/TopBar";
import { PipelineStepper, Stage } from "@/components/PipelineStepper";
import { MetricsPanel, StrategyMetrics } from "@/components/MetricsPanel";
import { HeightenedMonitoringBadge } from "@/components/HeightenedMonitoringBadge";
import { ChatPanel } from "@/components/ChatPanel";
import { AgentTradingDashboard } from "@/components/AgentTradingDashboard";
import { useStrategies } from "@/context/StrategyContext";
import {
  Activity, CheckCircle2, Database, FlaskConical, LayoutDashboard,
  MessageSquare, ShieldCheck, Cpu, Zap, TrendingUp,
} from "lucide-react";

function stageState(selected: any): Stage[] {
  const a = selected.spec?.agents ?? {};
  const approved = !!selected.spec?.approved;
  const s = (key: string): "complete" | "current" | "upcoming" => {
    if (a[key] === "complete") return "complete";
    if (["running","queued","current"].includes(a[key])) return "current";
    if (a[key] === "failed") return "current";
    return "upcoming";
  };
  const approval = approved ? "complete"
    : ["backtest_complete","indicator_complete","risk_complete","risk_ready"].includes(selected.status ?? "") ? "current"
    : "upcoming";
  const live = ["running","live_running"].includes(selected.spec?.live?.status ?? selected.spec?.pipeline_stage ?? "")
    ? "current" : selected.spec?.live?.status === "complete" ? "complete" : "upcoming";
  return [
    { label: "Research",   status: s("research") },
    { label: "Backtest",   status: s("backtest") },
    { label: "Indicators", status: s("indicator") },
    { label: "Risk",       status: s("risk") },
    { label: "Approval",   status: approval as any },
    { label: "Live",       status: live as any },
  ];
}

function fmtTime(v: string) {
  try { return new Date(v).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); } catch { return ""; }
}

function statusClass(status: string) {
  if (status === "failed") return "text-red-400";
  if (["running","blocked","current"].includes(status)) return "text-accent";
  return "text-text-muted";
}

// Agent tag colours
const AGENT_COLORS: Record<string, string> = {
  momentum:       "bg-blue-900/40 text-blue-300 border-blue-800/40",
  mean_reversion: "bg-purple-900/40 text-purple-300 border-purple-800/40",
  breakout:       "bg-orange-900/40 text-orange-300 border-orange-800/40",
  scalper:        "bg-yellow-900/40 text-yellow-300 border-yellow-800/40",
  sentiment:      "bg-teal-900/40 text-teal-300 border-teal-800/40",
};

export default function DashboardPage() {
  const { strategies, selectedId } = useStrategies();
  const [mobileTab, setMobileTab] = useState<"overview" | "chat">("overview");
  const selected = strategies.find(s => s.strategy_id === selectedId) ?? strategies[0];

  if (!selected) {
    return (
      <div className="flex h-screen flex-col bg-bg">
        <TopBar tier="PRO" />
        <div className="flex flex-1 overflow-hidden">
          <main className="flex min-w-0 flex-1 flex-col justify-center overflow-y-auto p-5 sm:p-8">
            <div className="mx-auto w-full max-w-2xl">
              <h1 className="text-2xl font-semibold tracking-tight">Build your first trading strategy</h1>
              <p className="mt-2 text-sm text-text-muted leading-6">
                Tell ManiQuantAI what you want to trade. Your strategy runs through a 6-agent team
                — Research, Backtest, Indicators, Risk, Approval, and Live execution through MetaTrader 5.
              </p>
              <div className="mt-6 rounded-xl border border-border bg-bg-panel p-5">
                <div className="text-xs text-text-muted mb-2">Try one of these:</div>
                {[
                  "BTC/USD 15m EMA 9/21 crossover, 1% risk, ATR stop",
                  "ETH/USD breakout above 20-bar resistance with volume, 1.5% risk",
                  "SOL/USD RSI 30 + lower Bollinger, 90 days backtest",
                  "XAU/USD scalping on 5m EMA 3/8, tight stop",
                ].map(ex => (
                  <div key={ex} className="mt-2 rounded-lg border border-border bg-bg-raised px-3 py-2 text-xs text-text-faint">
                    <span className="text-accent">✦</span> {ex}
                  </div>
                ))}
              </div>
            </div>
          </main>
          <aside className="hidden w-full flex-shrink-0 lg:block lg:w-[420px]">
            <ChatPanel onboarding />
          </aside>
        </div>
      </div>
    );
  }

  const spec      = selected.spec ?? {};
  const runtime   = spec.runtime ?? spec.parsed_strategy ?? {};
  const symbol    = runtime.symbol ?? "?";
  const tf        = runtime.timeframe ?? "?";
  const stype     = spec.strategy_type ?? "multi_signal";
  const activeAgents: string[] = spec.active_agents ?? [];
  const isLive    = spec.live_approved && ["live_running","running"].includes(spec.pipeline_stage ?? "");

  const metricsRaw = spec.backtest?.metrics;
  const metrics: StrategyMetrics | undefined = metricsRaw ? {
    status: "PASSED",
    winRate: Number(metricsRaw.win_rate ?? 0),
    tradeCount: Number(metricsRaw.trade_count ?? metricsRaw.total_trades ?? 0),
    winLossRatio: Number(metricsRaw.profit_factor ?? 0),
    sharpe: Number(metricsRaw.sharpe_ratio ?? 0),
    maxDrawdown: -Number(metricsRaw.max_drawdown_pct ?? 0),
  } : undefined;

  const pipeline  = spec.pipeline_stage ?? selected.status ?? "draft";
  const activity  = Array.isArray(spec.activity) ? [...spec.activity].reverse() : [];
  const criteria  = spec.backtest_criteria ?? spec.research_criteria ?? {};

  const description =
    pipeline === "awaiting_mt5_connection" ? "Connect your MetaTrader 5 account before the pipeline can start." :
    pipeline === "research_running" ? "Research Agent is analysing the strategy…" :
    pipeline === "research_complete" ? "Research complete — deterministic backtest ready for confirmation." :
    pipeline === "backtest_running" ? "Deterministic Backtest Agent is running historical tests…" :
    pipeline === "strategy_compilation_failed" ? `Strategy compilation needs recovery: ${spec.error ?? ""}` :
    pipeline === "indicator_running" ? "Indicator Agent verifying executable indicator definitions…" :
    pipeline === "risk_running" ? "Risk Management Agent validating deterministic risk controls…" :
    pipeline === "awaiting_live_approval" ? "All gates passed — live approval required." :
    pipeline === "live_running" || pipeline === "live_approved" ? `Agent team is live on ${symbol} ${tf}.` :
    pipeline === "backtest_complete" ? "Backtest complete — Indicator and Risk Agents next." :
    "Strategy saved — pipeline starting.";

  return (
    <div className="flex h-screen flex-col bg-bg">
      <TopBar tier="PRO" />
      <div className="flex flex-1 overflow-hidden">
        <main className={`flex-1 space-y-5 overflow-y-auto p-4 sm:p-6 ${mobileTab === "chat" ? "hidden lg:block" : "block"}`}>

          {/* Title row */}
          <div>
            <div className="mb-1 flex flex-wrap items-center gap-2 sm:gap-3">
              <h1 className="text-lg font-semibold sm:text-xl">{selected.name}</h1>
              {selected.heightened_monitoring_day && (
                <HeightenedMonitoringBadge
                  day={selected.heightened_monitoring_day}
                  totalDays={selected.heightened_monitoring_total!}
                />
              )}
              {isLive && (
                <span className="flex items-center gap-1.5 rounded-full bg-green-900/40 px-2.5 py-0.5 text-xs text-green-300">
                  <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
                  Live
                </span>
              )}
            </div>
            <p className="text-sm text-text-muted">{description}</p>
          </div>

          {/* Strategy type + agent tags */}
          {(stype !== "multi_signal" || activeAgents.length > 0) && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-accent/30 bg-accent/10 px-2.5 py-0.5 text-xs text-accent">
                {stype.replace("_", " ")}
              </span>
              {activeAgents.map(a => (
                <span key={a} className={`rounded-full border px-2.5 py-0.5 text-xs ${AGENT_COLORS[a] ?? "bg-bg-raised text-text-muted border-border"}`}>
                  {a.replace("_", " ")}
                </span>
              ))}
            </div>
          )}

          {/* Pipeline stepper */}
          <PipelineStepper stages={stageState(selected)} />

          {/* Pipeline activity */}
          <section className="rounded-lg border border-border bg-bg-panel p-5">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Activity size={17} className="text-accent" />
                <h2 className="text-sm font-medium">Pipeline activity</h2>
              </div>
              <span className="text-[11px] text-text-faint">Live</span>
            </div>
            {activity.length ? (
              <div className="space-y-3">
                {activity.map((item: any, i: number) => (
                  <div key={`${item.time}-${i}`} className="flex gap-3">
                    <div className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-bg-raised ${statusClass(item.status)}`}>
                      {item.status === "complete" ? <CheckCircle2 size={13} /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium text-text">{item.title}</p>
                        <span className="shrink-0 text-[10px] text-text-faint">{fmtTime(item.time)}</span>
                      </div>
                      <p className="mt-0.5 text-xs leading-5 text-text-muted">{item.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-text-faint">No pipeline activity yet. Start Research from the ManiQuantAI chat.</p>
            )}
          </section>

          {/* Backtest criteria */}
          <section className="rounded-lg border border-border bg-bg-panel p-5">
            <div className="mb-4 flex items-center gap-2">
              <FlaskConical size={17} className="text-accent" />
              <h2 className="text-sm font-medium">Strategy criteria</h2>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[
                ["Symbol", criteria.instrument ?? symbol ?? "—"],
                ["Timeframe", criteria.timeframe ?? tf ?? "—"],
                ["Lookback", `${criteria.lookback_days ?? runtime.lookback_days ?? "—"} days`],
                ["Risk", criteria.risk ?? `${runtime.risk_pct ?? "—"}% per trade`],
                ["Strategy type", stype.replace("_", " ")],
                ["Max positions", runtime.max_open_positions ?? 1],
              ].map(([label, value]) => (
                <div key={label as string} className="rounded-md border border-border bg-bg-raised p-3">
                  <div className="text-[10px] uppercase tracking-wide text-text-faint">{label}</div>
                  <div className="mt-1 text-sm font-medium">{value}</div>
                </div>
              ))}
            </div>
            {(criteria.entry ?? []).length > 0 && (
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="rounded-md border border-border bg-bg-raised p-3">
                  <div className="text-[10px] uppercase tracking-wide text-text-faint mb-1">Entry conditions</div>
                  {criteria.entry.map((x: string) => <div key={x} className="text-xs text-text-muted">• {x}</div>)}
                </div>
                <div className="rounded-md border border-border bg-bg-raised p-3">
                  <div className="text-[10px] uppercase tracking-wide text-text-faint mb-1">Exit conditions</div>
                  {(criteria.exit ?? []).map((x: string) => <div key={x} className="text-xs text-text-muted">• {x}</div>)}
                </div>
              </div>
            )}
          </section>

          {/* Backtest metrics */}
          {metrics && (
            <>
              <MetricsPanel metrics={metrics} />
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex items-center gap-2 rounded-lg border border-border bg-bg-panel px-4 py-3 text-xs text-text-muted">
                  <Database size={15} className="text-accent" />
                  Data source: <span className="text-text ml-1">{spec.backtest?.data_source ?? spec.data_source ?? "unknown"}</span>
                </div>
                <div className="flex items-center gap-2 rounded-lg border border-border bg-bg-panel px-4 py-3 text-xs text-text-muted">
                  <ShieldCheck size={15} className="text-accent" />
                  Bars tested: <span className="text-text ml-1">{Number(spec.bars_loaded ?? 0).toLocaleString()}</span>
                </div>
              </div>
            </>
          )}

          {/* Agent Trading Desk — shows when live approved */}
          {spec.live_approved && (
            <section className="rounded-lg border border-border bg-bg-panel p-5">
              <AgentTradingDashboard
                strategyId={selected.strategy_id}
                symbol={symbol !== "?" ? symbol : "BTCUSD"}
                timeframe={tf !== "?" ? tf : "15m"}
              />
            </section>
          )}

          {/* Agent status (pre-live) */}
          {!spec.live_approved && !metrics && (
            <div className="rounded-lg border border-border bg-bg-panel p-5">
              <div className="flex items-center gap-2 mb-3">
                <Cpu size={16} className="text-accent" />
                <div className="text-sm font-medium">Agent team</div>
              </div>
              <p className="text-sm text-text-muted mb-4">
                6 specialized agents validate your strategy before live execution.
              </p>
              <div className="grid gap-2 sm:grid-cols-2 text-xs text-text-faint">
                {[
                  ["Research Agent",       spec.agents?.research ?? "queued"],
                  ["Backtest Agent",       spec.agents?.backtest ?? "gated"],
                  ["Indicator Agent",      spec.agents?.indicator ?? "gated"],
                  ["Risk Agent",          spec.agents?.risk ?? "gated"],
                  ["Portfolio Manager",   spec.live_approved ? "active" : "gated"],
                  ["Live Execution",       spec.live_approved ? "running" : "gated"],
                ].map(([label, status]) => (
                  <div key={label as string} className="flex items-center justify-between rounded border border-border bg-bg-raised px-3 py-2">
                    <span>{label}</span>
                    <span className={status === "complete" || status === "active" || status === "running" ? "text-green-400" : status === "failed" ? "text-red-400" : status === "running" ? "text-accent" : "text-text-muted"}>
                      {status as string}
                    </span>
                  </div>
                ))}
              </div>
              {spec.error && (
                <div className="mt-3 rounded border border-red-800/40 bg-red-950/20 px-3 py-2 text-xs text-red-300">
                  {spec.error}
                </div>
              )}
            </div>
          )}

        </main>

        {/* Chat sidebar */}
        <aside className={`w-full flex-shrink-0 lg:w-[380px] ${mobileTab === "overview" ? "hidden lg:block" : "block"}`}>
          <ChatPanel strategyId={selected.strategy_id} />
        </aside>
      </div>

      {/* Mobile nav */}
      <nav className="flex border-t border-border lg:hidden">
        <button onClick={() => setMobileTab("overview")} className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs ${mobileTab === "overview" ? "text-accent" : "text-text-faint"}`}>
          <LayoutDashboard size={18} />Overview
        </button>
        <button onClick={() => setMobileTab("chat")} className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs ${mobileTab === "chat" ? "text-accent" : "text-text-faint"}`}>
          <MessageSquare size={18} />Chat
        </button>
      </nav>
    </div>
  );
}
