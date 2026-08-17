"use client";
import { useState } from "react";
import { X } from "lucide-react";
import { getAccessToken } from "@/lib/supabase";

export function ConnectMT5Modal({ open, onClose, onConnected }: {
  open: boolean;
  onClose: () => void;
  onConnected?: (accountId: string) => void;
}) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [server, setServer] = useState("");
  const [label, setLabel] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const loginNumber = parseInt(login, 10);
    if (!loginNumber || !password || !server) {
      setError("Login, password, and server are all required.");
      return;
    }

    setConnecting(true);
    try {
      const token = await getAccessToken();
      const res = await fetch("/api/broker-accounts/mt5", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          login: loginNumber,
          password,
          server,
          label: label || undefined,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Couldn't connect this account. Check your details and try again.");
      }

      const data = await res.json();
      onConnected?.(data.broker_account_id);
      setLogin("");
      setPassword("");
      setServer("");
      setLabel("");
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setConnecting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-md rounded-lg border border-border bg-bg-panel p-6">
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-base font-semibold">Connect MetaTrader 5</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <p className="mb-4 text-xs text-text-faint">
          Same login, password, and server your MT5 terminal already uses. Your password is
          encrypted before it&apos;s stored — we never see or log it in plain text.
        </p>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="mb-1 block text-xs text-text-muted">Login (account number)</label>
            <input
              type="text"
              inputMode="numeric"
              value={login}
              onChange={(e) => setLogin(e.target.value.replace(/\D/g, ""))}
              placeholder="12345678"
              className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-faint outline-none focus:border-accent"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs text-text-muted">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Your MT5 password"
              className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-faint outline-none focus:border-accent"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs text-text-muted">Server</label>
            <input
              type="text"
              value={server}
              onChange={(e) => setServer(e.target.value)}
              placeholder="e.g. Exness-Real, ICMarkets-Live01"
              className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-faint outline-none focus:border-accent"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs text-text-muted">Nickname (optional)</label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. My live account"
              className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-faint outline-none focus:border-accent"
            />
          </div>

          {error && <p className="text-sm text-danger">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border px-4 py-2 text-sm text-text-muted hover:bg-bg-raised"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={connecting}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg disabled:opacity-40"
            >
              {connecting ? "Connecting…" : "Connect account"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
