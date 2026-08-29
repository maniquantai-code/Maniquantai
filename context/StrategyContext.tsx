"use client";
import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { supabase, getAccessToken } from "@/lib/supabase";

export interface StrategySummary {
  strategy_id: string;
  name: string;
  status: string;
  fast_track: boolean;
  heightened_monitoring_day: number | null;
  heightened_monitoring_total: number | null;
  raw_strategy_text?: string;
  spec?: Record<string, any>;
}

interface StrategyContextValue {
  strategies: StrategySummary[];
  selectedId: string | null;
  selectStrategy: (id: string) => void;
  loading: boolean;
  createStrategy: (rawText: string) => Promise<void>;
  creating: boolean;
  createError: string | null;
}

const StrategyContext = createContext<StrategyContextValue | null>(null);

function deriveName(raw: string): string {
  const text = raw.trim().replace(/\s+/g, " ");
  const matches = text.match(
    /\b(?:BTC\s*\/\s*USD|ETH\s*\/\s*USD|SOL\s*\/\s*USD|XAU\s*\/\s*USD|[A-Z]{2,6}\s*\/\s*[A-Z]{2,6}|(?:EMA|RSI|ATR|MACD)\s*\(?\d+\)?)\b/gi
  ) ?? [];
  const ids = [...new Set(matches.map(m => m.toUpperCase().replace(/\s+/g, "")))];
  return (ids.length ? ids.slice(0, 3).join(" ") : text.split(/\s+/).slice(0, 6).join(" ")).slice(0, 48) || "Untitled Strategy";
}

export function StrategyProvider({ children }: { children: ReactNode }) {
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function fetchStrategies() {
    try {
      const { data: authData } = await supabase.auth.getUser();
      const userId = authData.user?.id;
      if (!userId) { setStrategies([]); setSelectedId(null); return; }
      const { data, error } = await supabase
        .from("strategies")
        .select("strategy_id,name,status,fast_track,heightened_monitoring_day,heightened_monitoring_total,raw_strategy_text,spec,created_at")
        .eq("user_id", userId)
        .order("created_at", { ascending: false });
      if (error) throw error;
      const rows = (data ?? []) as StrategySummary[];
      setStrategies(rows);
      setSelectedId(cur => cur && rows.some(s => s.strategy_id === cur) ? cur : rows[0]?.strategy_id ?? null);
    } catch { /* silent — no toast on background refresh */ }
    finally { setLoading(false); }
  }

  useEffect(() => {
    void fetchStrategies();
    // Poll every 3s so pipeline activity reflects in TopBar
    const t = window.setInterval(() => void fetchStrategies(), 3000);
    return () => window.clearInterval(t);
  }, []);

  async function kickoffChat(strategyId: string, rawText: string) {
    // Send the raw text as the first chat message so the compiler runs
    const token = await getAccessToken();
    if (!token) return;
    await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ strategy_id: strategyId, message: rawText }),
    }).catch(() => {}); // fire-and-forget — chat panel will show the result
  }

  async function createStrategy(rawText: string) {
    setCreating(true);
    setCreateError(null);
    try {
      const { data: authData } = await supabase.auth.getUser();
      const user = authData.user;
      if (!user) throw new Error("Please sign in before creating a strategy.");

      const strategyId = crypto.randomUUID();
      const ts = new Date().toISOString();
      const name = deriveName(rawText);

      const { data, error } = await supabase
        .from("strategies")
        .insert({
          strategy_id: strategyId,
          user_id: user.id,
          name,
          raw_strategy_text: rawText.trim(),
          status: "created",
          spec: {},
          fast_track: false,
          heightened_monitoring_day: null,
          heightened_monitoring_total: null,
          created_at: ts,
          updated_at: ts,
        })
        .select("strategy_id,name,status,fast_track,heightened_monitoring_day,heightened_monitoring_total,raw_strategy_text,spec")
        .single();

      if (error) {
        if (error.code === "23503") throw new Error("Profile not ready — sign out, sign back in, then retry.");
        if (error.code === "42501") throw new Error("Not authorized — refresh and sign in again.");
        if (error.code === "42703") throw new Error("Database needs updating — run the Supabase migration SQL.");
        throw new Error(error.message || "Could not save the strategy.");
      }

      const created = data as StrategySummary;
      setStrategies(cur => [created, ...cur.filter(s => s.strategy_id !== created.strategy_id)]);
      setSelectedId(created.strategy_id);

      // Kick off compilation + research via chat endpoint (non-blocking)
      void kickoffChat(created.strategy_id, rawText);

      // Refresh list so status updates appear
      setTimeout(() => void fetchStrategies(), 2000);

    } catch (e) {
      const msg = e instanceof Error ? e.message : "Could not save the strategy.";
      setCreateError(msg);
      throw new Error(msg);
    } finally {
      setCreating(false);
    }
  }

  return (
    <StrategyContext.Provider value={{
      strategies, selectedId, selectStrategy: setSelectedId,
      loading, createStrategy, creating, createError,
    }}>
      {children}
    </StrategyContext.Provider>
  );
}

export function useStrategies() {
  const ctx = useContext(StrategyContext);
  if (!ctx) throw new Error("useStrategies must be used within StrategyProvider");
  return ctx;
}
