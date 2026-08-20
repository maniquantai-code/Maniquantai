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
      if (!token) throw new Error("Please sign in before creating a strategy.");

      const res = await fetch("/api/strategies", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ raw_strategy_text: rawText }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(
          err.detail?.error === "quota_exceeded"
            ? `Out of credits for this action (needs ${err.detail.cost}, you have ${err.detail.balance}).`
            : typeof err.detail === "string"
              ? err.detail
              : "Couldn't create the strategy. Is the backend running?"
        );
      }

      const data = await res.json();

      // IMPORTANT: do not wait for a second GET request before opening the
      // dashboard. The POST already returned the durable strategy record.
      // Optimistically insert it and select it immediately so ChatPanel and
      // the rest of the dashboard render without a race with the GET.
      const created: StrategySummary = {
        strategy_id: data.strategy_id,
        name: data.name || "Untitled Strategy",
        status: data.status || "draft",
        fast_track: Boolean(data.fast_track),
        heightened_monitoring_day: data.heightened_monitoring_day ?? null,
        heightened_monitoring_total: data.heightened_monitoring_total ?? null,
        raw_strategy_text: rawText,
      };

      setStrategies((current) => [
        created,
        ...current.filter((s) => s.strategy_id !== created.strategy_id),
      ]);
      setSelectedId(created.strategy_id);

      // Refresh in the background for any server-side fields, but never block
      // the UI transition on this request.
      void fetchStrategiesPreservingSelection(created.strategy_id);
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Something went wrong.");
      throw e;
    } finally {
      setCreating(false);
    }
  }

  async function fetchStrategiesPreservingSelection(createdId: string) {
    try {
      const token = await getAccessToken();
      if (!token) return;
      const res = await fetch("/api/strategies", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return;
      const data = await res.json();
      if (!Array.isArray(data)) return;

      setStrategies((current) => {
        const serverStrategies = data as StrategySummary[];
        const merged = [...serverStrategies];
        for (const local of current) {
          if (!merged.some((s) => s.strategy_id === local.strategy_id)) merged.push(local);
        }
        return merged;
      });
      setSelectedId(createdId);
    } catch {
      // The strategy is already saved and visible locally; a background
      // refresh failure must not take the user back to the empty state.
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
