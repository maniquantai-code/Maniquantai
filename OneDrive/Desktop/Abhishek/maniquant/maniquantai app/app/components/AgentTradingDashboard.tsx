"use client";

/**
 * ManiQuantAI — Agent Trading Command Center
 *
 * Shows the 5-agent team in real time:
 *   • Momentum Agent      — EMA crossover + ADX
 *   • Mean Reversion Agent — RSI + Bollinger
 *   • Breakout Agent       — S/R + volume
 *   • Scalper Agent        — micro EMA + RSI(7)
 *   • Sentiment Agent      — SMA deviation + vol trend
 *   • Portfolio Manager    — consensus + final gate
 *
 * Polls /api/live-trading/agent-status/:id every 5 seconds when live.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import {
  Activity, AlertTriangle, ArrowDown, ArrowUp, CheckCircle2,
  Circle, Cpu, Minus, Shield, TrendingDown, TrendingUp, Wifi, WifiOff, Zap,
} from "lucide-react";
import { getAccessToken } from "@/lib/supabase";

// ─── Types ────────────────────────────────────────────────────────────────

interface AgentSignal {
  agent: string;
  signal: "BUY" | "SELL" | "HOLD" | "CLOSE_LONG" | "CLOSE_SHORT";
  strength: number;
  reason: string;
  stop_loss?: number;
  take_profit?: number;
  risk_pct?: number;
  meta?: Record<string, unknown>;
}

interface AgentScan {
  ts: string;
  signals: AgentSignal[];
  consensus: number;
  execute: boolean;
  reason: string;
}

interface AgentStatus {
  strategy_id: string;
  live_approved: boolean;
  live_status: string;
  last_agent_scan: AgentScan | null;
  agent_scans: AgentScan[];
  parsed_strategy: Record<string, unknown> | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────

const AGENT_META: Record<string, { label: string; icon: string; description: string }> = {
  momentum:      { label: "Momentum",      icon: "📈", description: "EMA 9/21 crossover · ADX filter" },
  mean_reversion:{ label: "Mean Reversion",icon: "↩",  description: "RSI + Bollinger oversold/overbought" },
  breakout:      { label: "Breakout",      icon: "💥", description: "S/R levels · volume confirmation" },
  scalper:       { label: "Scalper",       icon: "⚡", description: "EMA 3/8 · RSI(7) micro-structure" },
  sentiment:     { label: "Sentiment",     icon: "🧭", description: "SMA deviation · volume trend" },
};

function signalColor(signal: string) {
  if (signal === "BUY")  return "text-green-400";
  if (signal === "SELL") return "text-red-400";
  return "text-text-muted";
}

function signalBg(signal: string) {
  if (signal === "BUY")  return "bg-green-950/40 border-green-800/40";
  if (signal === "SELL") return "bg-red-950/40 border-red-800/40";
  return "bg-bg-raised border-border";
}

function SignalBadge({ signal }: { signal: string }) {
  const cls = signal === "BUY" ? "bg-green-900/60 text-green-300" :
              signal === "SELL" ? "bg-red-900/60 text-red-300" :
              "bg-bg-raised text-text-muted";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {signal === "BUY"  && <ArrowUp  size={10} />}
      {signal === "SELL" && <ArrowDown size={10} />}
      {signal === "HOLD" && <Minus    size={10} />}
      {signal}
    </span>
  );
}

function StrengthBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? "bg-green-500" : pct >= 40 ? "bg-yellow-500" : "bg-text-muted";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-bg-raised">
        <div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-text-muted">{pct}%</span>
    </div>
  );
}

function ConsensusGauge({ value }: { value: number }) {
  const abs = Math.abs(value);
  const bullish = value >= 0;
  const pct = Math.round(abs * 100);
  const color = abs >= 0.35 ? (bullish ? "bg-green-500" : "bg-red-500") : "bg-yellow-500";
  const direction = abs >= 0.35 ? (bullish ? "BUY" : "SELL") : "NEUTRAL";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-text-muted">Portfolio consensus</span>
        <span className={`font-semibold ${abs >= 0.35 ? (bullish ? "text-green-400" : "text-red-400") : "text-yellow-400"}`}>
          {direction} {value > 0 ? "+" : ""}{value.toFixed(3)}
        </span>
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-bg-raised">
        <div className="absolute left-1/2 h-full w-0.5 bg-border" />
        {bullish ? (
          <div className={`absolute left-1/2 h-full ${color} transition-all`} style={{ width: `${pct * 50}%` }} />
        ) : (
          <div className={`absolute right-1/2 h-full ${color} transition-all`} style={{ width: `${pct * 50}%` }} />
        )}
      </div>
      <div className="flex justify-between text-[10px] text-text-muted">
        <span>SELL -1.0</span>
        <span>NEUTRAL 0</span>
        <span>BUY +1.0</span>
      </div>
    </div>
  );
}

function formatTime(ts: string) {
  try { return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
  catch { return ""; }
}

// ─── Agent Card ───────────────────────────────────────────────────────────

function AgentCard({ sig, isLive }: { sig: AgentSignal; isLive: boolean }) {
  const meta = AGENT_META[sig.agent] ?? { label: sig.agent, icon: "🤖", description: "" };
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`rounded-xl border p-4 transition-all cursor-pointer ${signalBg(sig.signal)} ${isLive ? "ring-1 ring-accent/20" : ""}`}
      onClick={() => setExpanded(e => !e)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">{meta.icon}</span>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-text">{meta.label}</span>
              {isLive && <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />}
            </div>
            <p className="text-[10px] text-text-muted">{meta.description}</p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <SignalBadge signal={sig.signal} />
          <StrengthBar value={sig.strength} />
        </div>
      </div>

      {expanded && (
        <div className="mt-3 space-y-2 border-t border-border/40 pt-3">
          <p className="text-xs text-text-muted leading-5">{sig.reason}</p>
          {(sig.stop_loss || sig.take_profit) && (
            <div className="flex gap-4 text-xs">
              {sig.stop_loss  && <span className="text-red-400">SL {sig.stop_loss.toFixed(4)}</span>}
              {sig.take_profit && <span className="text-green-400">TP {sig.take_profit.toFixed(4)}</span>}
              {sig.risk_pct   && <span className="text-text-muted">Risk {sig.risk_pct}%</span>}
            </div>
          )}
          {sig.meta && Object.keys(sig.meta).length > 0 && (
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {Object.entries(sig.meta).map(([k, v]) => (
                <span key={k} className="text-[10px] text-text-muted">
                  <span className="text-text-faint">{k}:</span> {String(v)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Scan History Row ─────────────────────────────────────────────────────

function ScanHistoryRow({ scan, index }: { scan: AgentScan; index: number }) {
  const bull = scan.signals?.filter(s => s.signal === "BUY").length ?? 0;
  const bear = scan.signals?.filter(s => s.signal === "SELL").length ?? 0;
  const hold = scan.signals?.filter(s => s.signal === "HOLD").length ?? 0;

  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded-lg text-xs ${index === 0 ? "bg-accent/5 border border-accent/10" : "hover:bg-bg-raised"}`}>
      <span className="text-text-muted w-16 shrink-0">{formatTime(scan.ts)}</span>
      <div className="flex gap-2 shrink-0">
        {bull  > 0 && <span className="text-green-400">{bull}↑</span>}
        {bear  > 0 && <span className="text-red-400">{bear}↓</span>}
        {hold  > 0 && <span className="text-text-muted">{hold}–</span>}
      </div>
      <span className={`font-medium ${Math.abs(scan.consensus) >= 0.35 ? (scan.consensus > 0 ? "text-green-400" : "text-red-400") : "text-text-muted"}`}>
        {scan.consensus > 0 ? "+" : ""}{scan.consensus.toFixed(3)}
      </span>
      {scan.execute && (
        <span className="ml-auto rounded-full bg-green-900/50 px-2 py-0.5 text-green-300 text-[10px]">ORDER</span>
      )}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────

export function AgentTradingDashboard({ strategyId, symbol, timeframe }: {
  strategyId: string;
  symbol?: string;
  timeframe?: string;
}) {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const token = await getAccessToken();
      if (!token) return;
      const r = await fetch(`/api/live-trading/agent-status/${strategyId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error(await r.text());
      const data: AgentStatus = await r.json();
      setStatus(data);
      setLastRefresh(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch agent status");
    } finally {
      setLoading(false);
    }
  }, [strategyId]);

  const triggerScan = useCallback(async () => {
    setIsScanning(true);
    try {
      const token = await getAccessToken();
      if (!token) return;
      await fetch("/api/live-trading/execute", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_id: strategyId,
          symbol: symbol ?? "BTCUSD",
          timeframe: timeframe ?? "15m",
          bar_count: 300,
          current_position: "flat",
          account_equity: 10000,
        }),
      });
      await fetchStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setIsScanning(false);
    }
  }, [strategyId, symbol, timeframe, fetchStatus]);

  useEffect(() => {
    fetchStatus();
    // Auto-refresh every 5s when live
    intervalRef.current = setInterval(fetchStatus, 5000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [fetchStatus]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-text-muted">
        <Activity size={16} className="mr-2 animate-pulse text-accent" /> Loading agent team…
      </div>
    );
  }

  const scan = status?.last_agent_scan;
  const signals = scan?.signals ?? [];
  const consensus = scan?.consensus ?? 0;
  const isLive = status?.live_status === "running";
  const isApproved = status?.live_approved ?? false;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Cpu size={17} className="text-accent" />
          <h2 className="text-sm font-semibold">Agent Trading Desk</h2>
          {isLive && (
            <span className="flex items-center gap-1.5 rounded-full bg-green-900/40 px-2.5 py-0.5 text-xs text-green-300">
              <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
              Live
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {lastRefresh && (
            <span className="text-[10px] text-text-muted">
              {formatTime(lastRefresh.toISOString())}
            </span>
          )}
          {isApproved && (
            <button
              onClick={triggerScan}
              disabled={isScanning}
              className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-bg disabled:opacity-50"
            >
              <Zap size={12} />
              {isScanning ? "Scanning…" : "Scan Now"}
            </button>
          )}
        </div>
      </div>

      {/* Not approved state */}
      {!isApproved && (
        <div className="rounded-xl border border-yellow-800/40 bg-yellow-950/20 p-5">
          <div className="flex items-center gap-2 text-yellow-300">
            <Shield size={16} />
            <span className="text-sm font-medium">Approval required</span>
          </div>
          <p className="mt-1.5 text-xs leading-6 text-text-muted">
            The strategy must pass Research → Backtest → Indicator → Risk → Human Approval before the agent team goes live.
            Use the chat panel to progress through each gate.
          </p>
        </div>
      )}

      {/* Consensus gauge */}
      {scan && (
        <div className="rounded-xl border border-border bg-bg-panel p-4">
          <ConsensusGauge value={consensus} />
          {scan.execute && (
            <div className="mt-3 flex items-center gap-2 rounded-lg bg-green-900/30 border border-green-800/40 px-3 py-2">
              <CheckCircle2 size={14} className="text-green-400 shrink-0" />
              <span className="text-xs text-green-300">Portfolio Manager approved — order queued for MT5</span>
            </div>
          )}
          {!scan.execute && scan.reason && (
            <p className="mt-2 text-[11px] text-text-muted leading-5">{scan.reason}</p>
          )}
        </div>
      )}

      {/* Agent cards */}
      {signals.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {signals.map(sig => (
            <AgentCard key={sig.agent} sig={sig} isLive={isLive} />
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border p-8 text-center">
          <Cpu size={24} className="mx-auto mb-2 text-text-muted" />
          <p className="text-sm text-text-muted">No agent signals yet</p>
          <p className="mt-1 text-xs text-text-muted">
            {isApproved ? 'Click "Scan Now" to run the agent team.' : "Complete the pipeline to activate live scanning."}
          </p>
        </div>
      )}

      {/* Scan history */}
      {status?.agent_scans && status.agent_scans.length > 0 && (
        <div className="rounded-xl border border-border bg-bg-panel p-4">
          <div className="mb-3 flex items-center gap-2">
            <Activity size={14} className="text-accent" />
            <span className="text-xs font-medium">Scan history</span>
            <span className="ml-auto text-[10px] text-text-muted">{status.agent_scans.length} scans</span>
          </div>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {[...status.agent_scans].reverse().slice(0, 20).map((s, i) => (
              <ScanHistoryRow key={s.ts + i} scan={s} index={i} />
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-800/40 bg-red-950/20 p-3 text-xs text-red-300">
          <AlertTriangle size={12} className="inline mr-1.5" />{error}
        </div>
      )}
    </div>
  );
}
