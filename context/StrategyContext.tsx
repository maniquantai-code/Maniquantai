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

function deriveStrategyName(rawText: string): string {
  const text = rawText.trim().replace(/\s+/g, " ");
  const matches = text.match(/\b(?:BTC\s*\/\s*USD|ETH\s*\/\s*USD|[A-Z]{2,6}\s*\/\s*[A-Z]{2,6}|(?:EMA|SMA|RSI|ATR|MACD)\s*\(?\d+(?:\.\d+)?\)?)\b/gi) ?? [];
  const identifiers = [...new Set(matches.map((m) => m.toUpperCase().replace(/\s+/g, "")))];
  if (identifiers.length) return identifiers.slice(0, 3).join(" ").slice(0, 48);
  return text.split(/\s+/).slice(0, 6).join(" ").slice(0, 48) || "Untitled Strategy";
}

export function StrategyProvider({ children }: { children: ReactNode }) {
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function fetchStrategies() {
    setLoading(true);
    try {
      const token = await getAccessToken();
      if (!token) { setStrategies([]); setSelectedId(null); return; }

      const { data, error } = await supabase
        .from("strategies")
        .select("strategy_id,name,status,fast_track,heightened_monitoring_day,heightened_monitoring_total,raw_strategy_text,created_at")
        .eq("user_id", (await supabase.auth.getUser()).data.user?.id ?? "")
        .order("created_at", { ascending: false });
      if (error) throw error;

      const userStrategies = (data ?? []) as StrategySummary[];
      setStrategies(userStrategies);
      setSelectedId((current) => current && userStrategies.some((s) => s.strategy_id === current) ? current : userStrategies[0]?.strategy_id ?? null);
    } catch {
      setStrategies([]);
      setSelectedId(null);
    } finally { setLoading(false); }
  }

  useEffect(() => { void fetchStrategies(); }, []);

  async function createStrategy(rawText: string) {
    setCreating(true);
    setCreateError(null);
    try {
      const { data: authData } = await supabase.auth.getUser();
      const user = authData.user;
      if (!user) throw new Error("Please sign in before creating a strategy.");

      const strategyId = crypto.randomUUID();
      const now = new Date().toISOString();
      const name = deriveStrategyName(rawText);
      const payload = {
        strategy_id: strategyId,
        user_id: user.id,
        name,
        raw_strategy_text: rawText.trim(),
        status: "draft",
        fast_track: false,
        heightened_monitoring_day: null,
        heightened_monitoring_total: null,
        created_at: now,
        updated_at: now,
      };

      const { data, error } = await supabase
        .from("strategies")
        .insert(payload)
        .select("strategy_id,name,status,fast_track,heightened_monitoring_day,heightened_monitoring_total,raw_strategy_text")
        .single();

      if (error) {
        if (error.code === "23503") {
          throw new Error("Your profile is not ready yet. Please sign out and sign in again, then retry.");
        }
        if (error.code === "42501") {
          throw new Error("Your account is not authorized to create strategies. Please refresh and sign in again.");
        }
        throw new Error(error.message || "Could not save strategy.");
      }

      const created = data as StrategySummary;
      setStrategies((current) => [created, ...current.filter((s) => s.strategy_id !== created.strategy_id)]);
      setSelectedId(created.strategy_id);
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Could not save strategy.");
      throw e;
    } finally { setCreating(false); }
  }

  return (
    <StrategyContext.Provider value={{ strategies, selectedId, selectStrategy: setSelectedId, loading, createStrategy, creating, createError }}>
      {children}
    </StrategyContext.Provider>
  );
}

export function useStrategies() {
  const ctx = useContext(StrategyContext);
  if (!ctx) throw new Error("useStrategies must be used within StrategyProvider");
  return ctx;
}
