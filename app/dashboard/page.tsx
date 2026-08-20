"use client";
import { useEffect, useState } from "react";
import { TopBar } from "@/components/TopBar";
import { PipelineStepper, Stage } from "@/components/PipelineStepper";
import { MetricsPanel, StrategyMetrics } from "@/components/MetricsPanel";
import { HeightenedMonitoringBadge } from "@/components/HeightenedMonitoringBadge";
import { ChatPanel } from "@/components/ChatPanel";
import { useStrategies } from "@/context/StrategyContext";
import { MessageSquare, LayoutDashboard } from "lucide-react";

function stageState(selected:any): Stage[] {
 const a=selected.spec?.agents??{}; const paper=selected.spec?.paper_session; const approved=!!selected.spec?.approved;
 const research=a.research==="complete"?"complete":a.research==="failed"?"current":a.research==="running"?"current":"upcoming";
 const backtest=a.backtest==="complete"?"complete":a.backtest==="failed"?"current":a.backtest==="running"?"current":"upcoming";
 const paperStage=paper?.status==="running"?"current":approved?"upcoming":"upcoming";
 const approval=approved?"complete":selected.status==="backtest_complete"?"current":"upcoming";
 const live=selected.spec?.live?.status==="running"?"current":"upcoming";
 return [{label:"Research",status:research},{label:"Backtest",status:backtest},{label:"Paper",status:paperStage},{label:"Approval",status:approval},{label:"Live",status:live}];
}

export default function DashboardPage(){
 const {strategies,selectedId}=useStrategies();
 const [mobileTab,setMobileTab]=useState<"overview"|"chat">("overview");
 const selected=strategies.find(s=>s.strategy_id===selectedId)??strategies[0];
 const [, setTick]=useState(0);
 useEffect(()=>{
   if(!selectedId) return;
   const timer=window.setInterval(()=>setTick(v=>v+1),2000);
   return()=>window.clearInterval(timer);
 },[selectedId]);
 if(!selected)return <div className="flex h-screen flex-col bg-bg"><TopBar tier="PRO"/><div className="flex flex-1 overflow-hidden"><main className="flex min-w-0 flex-1 flex-col justify-center overflow-y-auto p-5 sm:p-8"><div className="mx-auto w-full max-w-2xl"><div className="mb-8"><div className="mb-2 flex items-center gap-2 text-accent"><span className="h-2 w-2 rounded-full bg-accent"/> Your workspace</div><h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Build your first trading strategy</h1><p className="mt-2 max-w-xl text-sm leading-6 text-text-muted">Tell ManiQuant AI what you want to trade. Your strategy will be saved and analyzed automatically.</p></div><div className="rounded-xl border border-border bg-bg-panel p-6 shadow-sm"><div className="flex items-start gap-4"><div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-accent-dim text-accent"><MessageSquare size={19}/></div><div><h2 className="font-medium">No strategies yet</h2><p className="mt-1 text-sm leading-6 text-text-muted">Start in the ManiQuant AI chat. It will guide your strategy through research, deterministic backtesting, validation, approval and paper trading.</p></div></div><div className="mt-5 rounded-lg border border-border bg-bg-raised px-4 py-3 text-sm text-text-faint"><span className="text-accent">✦</span> Try: “Create a BTC/USD 15-minute EMA 9/21 crossover strategy and backtest the last 90 days.”</div></div></div></main><aside className="hidden w-full flex-shrink-0 lg:block lg:w-[420px]"><ChatPanel onboarding/></aside></div><nav className="border-t border-border lg:hidden"><button onClick={()=>setMobileTab("chat")} className="flex w-full items-center justify-center gap-2 py-3 text-sm text-accent"><MessageSquare size={18}/> Chat with ManiQuant AI</button></nav></div>;
 const spec=selected.spec??{}; const metricsRaw=spec.backtest?.metrics;
 const metrics:StrategyMetrics|undefined=metricsRaw?{status:"PASSED",winRate:Number(metricsRaw.win_rate??0),tradeCount:Number(metricsRaw.trade_count??0),winLossRatio:Number(metricsRaw.win_loss_ratio??0),sharpe:0,maxDrawdown:-Number(metricsRaw.max_drawdown_pct??0)}:undefined;
 const pipeline=spec.pipeline_stage??selected.status??"draft";
 const description=pipeline==="research"?"Research agent is analysing your strategy…":pipeline==="backtest_running"||pipeline==="backtesting"?"Backtest agent is running deterministic historical tests…":pipeline==="indicator_verification"?"Indicator agent is verifying the compiled indicators…":pipeline==="paper_trading"?"Paper-trading agent is monitoring the strategy…":pipeline==="paper_ready"?"Backtest complete · awaiting human approval before paper trading":pipeline==="backtest_complete"?"Backtest complete · review the results and approve the strategy":pipeline==="backtest_failed"?`Backtest failed: ${spec.error??"unknown error"}`:pipeline==="research_failed"?`Research failed: ${spec.error??"unknown error"}`:"Strategy saved · analysis pipeline is starting";
 return <div className="flex h-screen flex-col bg-bg"><TopBar tier="PRO"/><div className="flex flex-1 overflow-hidden"><main className={`flex-1 space-y-5 overflow-y-auto p-4 sm:p-6 ${mobileTab==="chat"?"hidden lg:block":"block"}`}><div><div className="mb-1 flex flex-wrap items-center gap-2 sm:gap-3"><h1 className="text-lg font-semibold sm:text-xl">{selected.name}</h1>{selected.heightened_monitoring_day&&selected.heightened_monitoring_total&&<HeightenedMonitoringBadge day={selected.heightened_monitoring_day} totalDays={selected.heightened_monitoring_total}/>}</div><p className="text-sm text-text-muted">{description}</p></div><PipelineStepper stages={stageState(selected)}/>{metrics?<MetricsPanel metrics={metrics}/>:<div className="rounded-lg border border-border bg-bg-panel p-5"><div className="text-sm font-medium">Analysis in progress</div><p className="mt-1 text-sm text-text-muted">No performance numbers are shown until the deterministic backtest engine has produced them.</p><div className="mt-4 grid gap-2 text-xs text-text-faint sm:grid-cols-2"><div>Research agent: {spec.agents?.research??"queued"}</div><div>Backtest agent: {spec.agents?.backtest??"queued"}</div><div>Indicator agent: {spec.agents?.indicator??"queued"}</div><div>Paper agent: {spec.agents?.paper??"gated"}</div>{spec.error&&<div className="sm:col-span-2 text-red-400">Error: {spec.error}</div>}</div></div>}</main><aside className={`w-full flex-shrink-0 lg:w-[380px] ${mobileTab==="overview"?"hidden lg:block":"block"}`}><ChatPanel strategyId={selected.strategy_id}/></aside></div><nav className="flex border-t border-border lg:hidden"><button onClick={()=>setMobileTab("overview")} className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs ${mobileTab==="overview"?"text-accent":"text-text-faint"}`}><LayoutDashboard size={18}/>Overview</button><button onClick={()=>setMobileTab("chat")} className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs ${mobileTab==="chat"?"text-accent":"text-text-faint"}`}><MessageSquare size={18}/>Chat</button></nav></div>;
}
