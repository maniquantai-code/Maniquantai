"use client";

import { useState } from "react";
import { TopBar } from "@/components/TopBar";
import { PipelineStepper, Stage } from "@/components/PipelineStepper";
import { MetricsPanel, StrategyMetrics } from "@/components/MetricsPanel";
import { HeightenedMonitoringBadge } from "@/components/HeightenedMonitoringBadge";
import { ChatPanel } from "@/components/ChatPanel";
import { useStrategies } from "@/context/StrategyContext";
import { Activity, CheckCircle2, Database, FlaskConical, LayoutDashboard, MessageSquare, ShieldCheck } from "lucide-react";

function stageState(selected: any): Stage[] {
  const a = selected.spec?.agents ?? {};
  const paper = selected.spec?.paper_session;
  const approved = !!selected.spec?.approved;
  const research = a.research === "complete" ? "complete" : a.research === "failed" ? "current" : ["running", "queued"].includes(a.research) ? "current" : "upcoming";
  const backtest = a.backtest === "complete" ? "complete" : a.backtest === "failed" ? "current" : ["running", "queued"].includes(a.backtest) ? "current" : "upcoming";
  const paperStage = paper?.status === "running" || a.paper === "current" ? "current" : a.paper === "complete" ? "complete" : "upcoming";
  const approval = approved ? "complete" : selected.status === "backtest_complete" ? "current" : "upcoming";
  const live = selected.spec?.live?.status === "running" ? "current" : selected.spec?.live?.status === "complete" ? "complete" : "upcoming";
  return [
    { label: "Research", status: research as any },
    { label: "Backtest", status: backtest as any },
    { label: "Paper", status: paperStage as any },
    { label: "Approval", status: approval as any },
    { label: "Live", status: live as any },
  ];
}

function formatTime(value: string) {
  try {
    return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function statusClass(status: string) {
  if (status === "failed") return "text-red-400";
  if (status === "running" || status === "blocked") return "text-accent";
  return "text-text-muted";
}

export default function DashboardPage() {
  const { strategies, selectedId } = useStrategies();
  const [mobileTab, setMobileTab] = useState<"overview" | "chat">("overview");
  const selected = strategies.find((s) => s.strategy_id === selectedId) ?? strategies[0];

  if (!selected) {
    return <div className="flex h-screen flex-col bg-bg"><TopBar tier="PRO"/><div className="flex flex-1 overflow-hidden"><main className="flex min-w-0 flex-1 flex-col justify-center overflow-y-auto p-5 sm:p-8"><div className="mx-auto w-full max-w-2xl"><div className="mb-8"><div className="mb-2 flex items-center gap-2 text-accent"><span className="h-2 w-2 rounded-full bg-accent"/> Your workspace</div><h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Build your first trading strategy</h1><p className="mt-2 max-w-xl text-sm leading-6 text-text-muted">Tell ManiQuant AI what you want to trade. Your strategy will be saved and analyzed automatically.</p></div><div className="rounded-xl border border-border bg-bg-panel p-6 shadow-sm"><div className="flex items-start gap-4"><div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-accent-dim text-accent"><MessageSquare size={19}/></div><div><h2 className="font-medium">No strategies yet</h2><p className="mt-1 text-sm leading-6 text-text-muted">Start in the ManiQuant AI chat. It will guide your strategy through research, deterministic backtesting, validation, approval and paper trading.</p></div></div><div className="mt-5 rounded-lg border border-border bg-bg-raised px-4 py-3 text-sm text-text-faint"><span className="text-accent">✦</span> Try: “Create a BTC/USD 15-minute EMA 9/21 crossover strategy and backtest the last 90 days.”</div></div></div></main><aside className="hidden w-full flex-shrink-0 lg:block lg:w-[420px]"><ChatPanel onboarding/></aside></div><nav className="border-t border-border lg:hidden"><button onClick={()=>setMobileTab("chat")} className="flex w-full items-center justify-center gap-2 py-3 text-sm text-accent"><MessageSquare size={18}/> Chat with ManiQuant AI</button></nav></div>;
  }

  const spec = selected.spec ?? {};
  const metricsRaw = spec.backtest?.metrics;
  const metrics: StrategyMetrics | undefined = metricsRaw ? {
    status: "PASSED",
    winRate: Number(metricsRaw.win_rate ?? 0),
    tradeCount: Number(metricsRaw.trade_count ?? metricsRaw.total_trades ?? 0),
    winLossRatio: Number(metricsRaw.profit_factor ?? 0),
    sharpe: Number(metricsRaw.sharpe_ratio ?? 0),
    maxDrawdown: -Number(metricsRaw.max_drawdown_pct ?? 0),
  } : undefined;
  const pipeline = spec.pipeline_stage ?? selected.status ?? "draft";
  const description = pipeline === "awaiting_mt5_connection" ? "Connect your MetaTrader 5 account before the strategy pipeline can start.": pipeline === "research_running" || pipeline === "research_queued" ? "Research Agent is analysing the strategy and validating the requested conditions…": pipeline === "research_complete" || pipeline === "awaiting_backtest_confirmation" ? "Research is complete · deterministic backtest is ready for your confirmation.": pipeline === "backtest_running" || pipeline === "backtesting" ? "Deterministic Backtest Agent is running historical tests…": pipeline === "paper_ready" ? "Backtest complete · human approval recorded · paper trading is ready.": pipeline === "backtest_complete" ? "Backtest complete · review the results and approve the strategy": pipeline === "backtest_failed" ? `Backtest failed: ${spec.error ?? "unknown error"}`: pipeline === "research_failed" ? `Research failed: ${spec.error ?? "unknown error"}`: pipeline === "paper_complete" ? "Paper trading complete · live execution is now gated.": "Strategy saved · analysis pipeline is starting";

  const criteria = spec.backtest_criteria ?? spec.research_criteria ?? {};
  const research = spec.research ?? {};
  const activity = Array.isArray(spec.activity) ? [...spec.activity].reverse() : [];

  return <div className="flex h-screen flex-col bg-bg"><TopBar tier="PRO"/><div className="flex flex-1 overflow-hidden"><main className={`flex-1 space-y-5 overflow-y-auto p-4 sm:p-6 ${mobileTab === "chat" ? "hidden lg:block" : "block"}`}>
    <div><div className="mb-1 flex flex-wrap items-center gap-2 sm:gap-3"><h1 className="text-lg font-semibold sm:text-xl">{selected.name}</h1>{selected.heightened_monitoring_day&&selected.heightened_monitoring_total&&<HeightenedMonitoringBadge day={selected.heightened_monitoring_day} totalDays={selected.heightened_monitoring_total}/>}</div><p className="text-sm text-text-muted">{description}</p></div>
    <PipelineStepper stages={stageState(selected)}/>

    <section className="rounded-lg border border-border bg-bg-panel p-5">
      <div className="mb-4 flex items-center justify-between"><div className="flex items-center gap-2"><Activity size={17} className="text-accent"/><h2 className="text-sm font-medium">Pipeline activity</h2></div><span className="text-[11px] text-text-faint">Live</span></div>
      {activity.length ? <div className="space-y-3">{activity.map((item:any, i:number)=><div key={`${item.time}-${i}`} className="flex gap-3"><div className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-bg-raised ${statusClass(item.status)}`}>{item.status === "complete" ? <CheckCircle2 size={13}/> : <span className="h-1.5 w-1.5 rounded-full bg-current"/>}</div><div className="min-w-0 flex-1"><div className="flex items-center justify-between gap-2"><p className="text-xs font-medium text-text">{item.title}</p><span className="shrink-0 text-[10px] text-text-faint">{formatTime(item.time)}</span></div><p className="mt-0.5 text-xs leading-5 text-text-muted">{item.detail}</p></div></div>)}</div> : <p className="text-xs text-text-faint">No pipeline activity yet. Start Research from the ManiQuant AI chat.</p>}
    </section>

    <section className="rounded-lg border border-border bg-bg-panel p-5">
      <div className="mb-4 flex items-center gap-2"><FlaskConical size={17} className="text-accent"/><h2 className="text-sm font-medium">Deterministic backtest criteria</h2></div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-md border border-border bg-bg-raised p-3"><div className="text-[10px] uppercase tracking-wide text-text-faint">Instrument</div><div className="mt-1 text-sm font-medium">{criteria.instrument ?? spec.parsed_strategy?.symbol ?? "—"}</div></div>
        <div className="rounded-md border border-border bg-bg-raised p-3"><div className="text-[10px] uppercase tracking-wide text-text-faint">Timeframe</div><div className="mt-1 text-sm font-medium">{criteria.timeframe ?? spec.parsed_strategy?.timeframe ?? "—"}</div></div>
        <div className="rounded-md border border-border bg-bg-raised p-3"><div className="text-[10px] uppercase tracking-wide text-text-faint">Lookback</div><div className="mt-1 text-sm font-medium">{criteria.lookback_days ?? spec.parsed_strategy?.lookback_days ?? "—"} days</div></div>
        <div className="rounded-md border border-border bg-bg-raised p-3"><div className="text-[10px] uppercase tracking-wide text-text-faint">Entry</div><div className="mt-1 space-y-1 text-xs text-text-muted">{(criteria.entry ?? []).length ? criteria.entry.map((x:string)=><div key={x}>• {x}</div>) : <div>—</div>}</div></div>
        <div className="rounded-md border border-border bg-bg-raised p-3"><div className="text-[10px] uppercase tracking-wide text-text-faint">Exit</div><div className="mt-1 space-y-1 text-xs text-text-muted">{(criteria.exit ?? []).length ? criteria.exit.map((x:string)=><div key={x}>• {x}</div>) : <div>—</div>}</div></div>
        <div className="rounded-md border border-border bg-bg-raised p-3"><div className="text-[10px] uppercase tracking-wide text-text-faint">Risk</div><div className="mt-1 text-sm font-medium">{criteria.risk ?? `${spec.parsed_strategy?.risk_pct ?? "—"}% per trade`}</div></div>
      </div>
    </section>

    {metrics ? <><MetricsPanel metrics={metrics}/><div className="grid gap-3 sm:grid-cols-2"><div className="flex items-center gap-2 rounded-lg border border-border bg-bg-panel px-4 py-3 text-xs text-text-muted"><Database size={15} className="text-accent"/>Data source: <span className="text-text">{spec.backtest?.data_source ?? spec.data_source ?? "unknown"}</span></div><div className="flex items-center gap-2 rounded-lg border border-border bg-bg-panel px-4 py-3 text-xs text-text-muted"><ShieldCheck size={15} className="text-accent"/>Bars tested: <span className="text-text">{Number(spec.bars_loaded ?? research.bars_checked ?? 0).toLocaleString()}</span></div></div><div className="rounded-lg border border-border bg-bg-panel px-4 py-3 text-xs text-text-muted">Period: <span className="text-text">{spec.backtest?.period_days ?? criteria.lookback_days ?? 0}d</span> · Interval: <span className="text-text">{spec.backtest?.timeframe ?? criteria.timeframe ?? ""}</span> · Trades: <span className="text-text">{Number(metricsRaw?.trade_count ?? metricsRaw?.total_trades ?? 0)}</span></div></> : <div className="rounded-lg border border-border bg-bg-panel p-5"><div className="text-sm font-medium">Analysis status</div><p className="mt-1 text-sm text-text-muted">The dashboard now shows agent activity and the exact deterministic criteria even before performance metrics are available.</p><div className="mt-4 grid gap-2 text-xs text-text-faint sm:grid-cols-2"><div>Research agent: {spec.agents?.research ?? "queued"}</div><div>Backtest agent: {spec.agents?.backtest ?? "gated"}</div><div>Indicator agent: {spec.agents?.indicator ?? "gated"}</div><div>Paper agent: {spec.agents?.paper ?? "gated"}</div>{spec.error&&<div className="sm:col-span-2 text-red-400">{spec.error}</div>}</div></div>}
  </main><aside className={`w-full flex-shrink-0 lg:w-[380px] ${mobileTab === "overview" ? "hidden lg:block" : "block"}`}><ChatPanel strategyId={selected.strategy_id}/></aside></div><nav className="flex border-t border-border lg:hidden"><button onClick={()=>setMobileTab("overview")} className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs ${mobileTab === "overview" ? "text-accent" : "text-text-faint"}`}><LayoutDashboard size={18}/>Overview</button><button onClick={()=>setMobileTab("chat")} className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs ${mobileTab === "chat" ? "text-accent" : "text-text-faint"}`}><MessageSquare size={18}/>Chat</button></nav></div>;
}
