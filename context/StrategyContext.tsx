"use client";
import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { getAccessToken } from "@/lib/supabase";

export interface StrategySummary {
  strategy_id: string;
  name: string;
  status: string;
  fast_track: boolean;
  heightened_monitoring_day: number | null;
  heightened_monitoring_total: number | null;
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

export function StrategyProvider({ children }: { children: ReactNode }) {
  // Only authenticated /api/strategies results are shown here.
  // No demo/sample strategies are seeded into the selector.
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function fetchStrategies() {
    setLoading(true);
    try {
      const token = await getAccessToken();
      if (!token) {
        setStrategies([]);
        setSelectedId(null);
        return;
      }

      const res = await fetch("/api/strategies", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to fetch strategies");

      const data = await res.json();
      const userStrategies = Array.isArray(data) ? data : [];
      setStrategies(userStrategies);
      setSelectedId((current) =>
        current && userStrategies.some((s: StrategySummary) => s.strategy_id === current)
          ? current
          : userStrategies[0]?.strategy_id ?? null
      );
    } catch {
      setStrategies([]);
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchStrategies();
  }, []);

  async function createStrategy(rawText: string) {
    setCreating(true);
    setCreateError(null);
    try {
      const token = await getAccessToken();
      const res = await fetch("/api/strategies", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ raw_strategy_text: rawText }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail?.error === "quota_exceeded"
          ? `Out of credits for this action (needs ${err.detail.cost}, you have ${err.detail.balance}).`
          : "Couldn't create the strategy. Is the backend running?");
      }
      const data = await res.json();
      await fetchStrategies();
      setSelectedId(data.strategy_id);
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <StrategyContext.Provider
      value={{
        strategies,
        selectedId,
        selectStrategy: setSelectedId,
        loading,
        createStrategy,
        creating,
        createError,
      }}
    >
      {children}
    </StrategyContext.Provider>
  );
}

export function useStrategies() {
  const ctx = useContext(StrategyContext);
  if (!ctx) throw new Error("useStrategies must be used within StrategyProvider");
  return ctx;
}
