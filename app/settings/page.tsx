"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, LogOut, Plus, Trash2, Wifi } from "lucide-react";
import { supabase, getAccessToken } from "@/lib/supabase";
import { useRouter } from "next/navigation";
import { ConnectMT5Modal } from "@/components/ConnectMT5Modal";

interface Wallet {
  balance: number;
  monthly_allowance: number;
  reset_date: string | null;
}

interface BrokerAccount {
  id: string;
  connector_type: string;
  connector_name: string;
  label: string | null;
  created_at: string;
}

const TIERS = [
  { name: "Free", priceIndia: "₹0", priceIntl: "$0", credits: 80 },
  { name: "Starter", priceIndia: "₹299", priceIntl: "$20", credits: 500 },
  { name: "Pro", priceIndia: "₹699", priceIntl: "$49", credits: 1500 },
  { name: "Elite", priceIndia: "₹1,499", priceIntl: "$99", credits: 4000 },
];

export default function SettingsPage() {
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [accounts, setAccounts] = useState<BrokerAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [connectOpen, setConnectOpen] = useState(false);
  const router = useRouter();

  async function fetchAll() {
    try {
      const token = await getAccessToken();
      if (!token) {
        setLoading(false);
        return;
      }
      const [walletRes, accountsRes] = await Promise.all([
        fetch("/api/wallet", { headers: { Authorization: `Bearer ${token}` } }),
        fetch("/api/broker-accounts", { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (walletRes.ok) setWallet(await walletRes.json());
      if (accountsRes.ok) setAccounts(await accountsRes.json());
    } catch {
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchAll();
  }, []);

  async function handleSignOut() {
    await supabase.auth.signOut();
    router.push("/login");
  }

  async function handleDisconnect(accountId: string) {
    const token = await getAccessToken();
    await fetch(`/api/broker-accounts/${accountId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    setAccounts((a) => a.filter((acc) => acc.id !== accountId));
  }

  const usedPercent = wallet
    ? Math.round(((wallet.monthly_allowance - wallet.balance) / wallet.monthly_allowance) * 100)
    : 0;
  const isLowOrOut = wallet ? wallet.balance / wallet.monthly_allowance < 0.15 : false;
  const currentTierName = wallet
    ? TIERS.find((t) => t.credits === wallet.monthly_allowance)?.name ?? "Free"
    : "Free";

  return (
    <div className="min-h-screen bg-bg">
      <header className="flex items-center gap-3 border-b border-border px-4 py-3 sm:px-6">
        <Link href="/dashboard" className="text-text-muted hover:text-text" aria-label="Back">
          <ArrowLeft size={18} />
        </Link>
        <span className="font-semibold">Settings & billing</span>
      </header>

      <div className="mx-auto max-w-2xl space-y-6 p-4 sm:p-6">
        <section className="rounded-lg border border-border bg-bg-panel p-5">
          <h2 className="mb-3 text-xs uppercase tracking-wide text-text-muted">
            Credit balance
          </h2>
          {loading ? (
            <p className="text-sm text-text-faint">Loading…</p>
          ) : wallet ? (
            <>
              <div className="mb-2 flex items-baseline justify-between">
                <span className="text-2xl font-semibold">{wallet.balance}</span>
                <span className="text-sm text-text-muted">/ {wallet.monthly_allowance} credits</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-bg-raised">
                <div
                  className={`h-full rounded-full transition-all ${isLowOrOut ? "bg-warn" : "bg-accent"}`}
                  style={{ width: `${100 - usedPercent}%` }}
                />
              </div>
              {wallet.reset_date && (
                <p className="mt-2 text-xs text-text-faint">
                  Resets {new Date(wallet.reset_date).toLocaleDateString()}
                </p>
              )}
              {isLowOrOut && (
                <div className="mt-3 rounded-lg border border-warn/30 bg-warn-dim p-3">
                  <p className="text-sm text-warn">
                    {wallet.balance === 0
                      ? "You're out of credits for this cycle."
                      : "Running low on credits."}{" "}
                    {currentTierName === "Free"
                      ? "Upgrade to Starter for a bigger monthly allowance and Claude-powered analysis."
                      : "Upgrade for more credits and higher limits."}
                  </p>
                  <button className="mt-2 rounded-md bg-warn px-3 py-1.5 text-xs font-medium text-bg">
                    View plans
                  </button>
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-text-faint">
              Couldn&apos;t load balance — sign in and make sure the backend is reachable.
            </p>
          )}
        </section>

        <section className="rounded-lg border border-border bg-bg-panel p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-xs uppercase tracking-wide text-text-muted">
              Linked trading accounts
            </h2>
            <button
              onClick={() => setConnectOpen(true)}
              className="flex items-center gap-1 rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-bg"
            >
              <Plus size={12} /> Connect MT5
            </button>
          </div>

          {accounts.length === 0 ? (
            <p className="text-sm text-text-faint">
              No trading accounts linked yet. Connect a MetaTrader 5 account to enable live
              execution once a strategy is approved.
            </p>
          ) : (
            <div className="space-y-2">
              {accounts.map((acc) => (
                <div
                  key={acc.id}
                  className="flex items-center justify-between rounded-lg border border-border p-3"
                >
                  <div className="flex items-center gap-2">
                    <Wifi size={14} className="text-accent" />
                    <div>
                      <div className="text-sm">{acc.label || acc.connector_name}</div>
                      <div className="text-xs text-text-faint">{acc.connector_name}</div>
                    </div>
                  </div>
                  <button
                    onClick={() => handleDisconnect(acc.id)}
                    className="text-text-faint hover:text-danger"
                    aria-label="Disconnect"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
          <p className="mt-3 text-xs text-text-faint">
            Your password is encrypted before storage — we never see or log it in plain text.
          </p>
        </section>

        <section className="rounded-lg border border-border bg-bg-panel p-5">
          <h2 className="mb-3 text-xs uppercase tracking-wide text-text-muted">Your plan</h2>
          <div className="space-y-2">
            {TIERS.map((tier) => (
              <div
                key={tier.name}
                className={`flex items-center justify-between rounded-lg border p-3 ${
                  tier.name === currentTierName ? "border-accent bg-accent-dim" : "border-border"
                }`}
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{tier.name}</span>
                    {tier.name === currentTierName && (
                      <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-medium text-bg">
                        Current
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-text-faint">{tier.credits} credits/month</span>
                </div>
                <div className="text-right text-sm text-text-muted">
                  {tier.priceIndia} <span className="text-text-faint">/</span> {tier.priceIntl}
                </div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-text-faint">
            Credits are an internal usage unit, not a currency conversion — they cover
            research, backtesting, and chat depth. Trading safety mechanisms are identical
            at every tier.
          </p>
        </section>

        <button
          onClick={handleSignOut}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-border py-2.5 text-sm text-text-muted hover:bg-bg-raised"
        >
          <LogOut size={14} /> Sign out
        </button>
      </div>

      <ConnectMT5Modal
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        onConnected={() => fetchAll()}
      />
    </div>
  );
}
