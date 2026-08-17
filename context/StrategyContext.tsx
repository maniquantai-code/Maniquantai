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

const DEMO_STRATEGIES: StrategySummary[] = [
  {
    strategy_id: "demo-eurusd",
    name: "EUR/USD Mean Reversion",
    status: "paper_trade",
    fast_track: true,
    heightened_monitoring_day: 4,
    heightened_monitoring_total: 14,
  },
  {
    strategy_id: "demo-btc",
    name: "BTC Momentum Breakout",
    status: "pending_backtest",
    fast_track: false,
    heightened_monitoring_day: null,
    heightened_monitoring_total: null,
  },
  {
    strategy_id: "demo-eth-rsi",
    name: "ETH RSI Reversal",
    status: "backtest_failed",
    fast_track: false,
    heightened_monitoring_day: null,
    heightened_monitoring_total: null,
  },
];

export function StrategyProvider({ children }: { children: ReactNode }) {
  const [strategies, setStrategies] = useState<StrategySummary[]>(DEMO_STRATEGIES);
  const [selectedId, setSelectedId] = useState<string | null>(DEMO_STRATEGIES[0].strategy_id);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function fetchStrategies() {
    setLoading(true);
    try {
      const token = await getAccessToken();
      if (!token) {
        setLoading(false);
        return;
      }
      const res = await fetch("/api/strategies", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to fetch strategies");
      const data = await res.json();
      if (Array.isArray(data) && data.length > 0) {
        setStrategies(data);
        setSelectedId(data[0].strategy_id);
      }
    } catch {
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
