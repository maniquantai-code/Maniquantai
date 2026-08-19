"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, Zap } from "lucide-react";
import { supabase } from "@/lib/supabase";

const PLANS = [
  { name: "Free", monthlyINR: 0, monthlyUSD: 0, annualINR: 0, annualUSD: 0, tag: null, cta: "Start free", credits: "80 credits / mo", workflows: "1 active workflow" },
  { name: "Starter", monthlyINR: 299, monthlyUSD: 20, annualINR: 249, annualUSD: 17, tag: null, cta: "Get started", credits: "500 credits / mo", workflows: "3 active workflows" },
  { name: "Pro", monthlyINR: 699, monthlyUSD: 49, annualINR: 583, annualUSD: 41, tag: "Most popular", cta: "Go Pro", credits: "1,500 credits / mo", workflows: "10 active workflows" },
  { name: "Elite", monthlyINR: 1499, monthlyUSD: 99, annualINR: 1249, annualUSD: 83, tag: null, cta: "Go Elite", credits: "4,000 credits / mo", workflows: "Unlimited workflows" },
];

const FEATURES = [
  "MT5, Delta Exchange & CoinSwitch",
  "Live trade execution",
  "Backtest & paper trading",
  "Capital preservation guardrails",
];

export default function LandingPage() {
  const [checkingSession, setCheckingSession] = useState(true);
  const [currency, setCurrency] = useState<"INR" | "USD">("INR");
  const [billing, setBilling] = useState<"monthly" | "annual">("monthly");
  const router = useRouter();

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) router.replace("/dashboard");
      else setCheckingSession(false);
    });
  }, [router]);

  if (checkingSession) return null;

  return (
    <div className="min-h-screen bg-bg text-text">
      <header className="sticky top-0 z-30 border-b border-border/60 bg-bg/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-dim text-accent"><span className="text-xs font-bold">M</span></div>
            <span className="font-semibold tracking-tight">ManiQuantAI</span>
          </div>
          <nav className="flex items-center gap-4">
            <a href="#pricing" className="hidden text-sm text-text-muted hover:text-text sm:block">Pricing</a>
            <Link href="/login" className="text-sm text-text-muted hover:text-text">Sign in</Link>
            <Link href="/login" className="rounded-lg bg-accent px-3.5 py-1.5 text-sm font-medium text-bg hover:bg-accent-muted">Get started</Link>
          </nav>
        </div>
      </header>

      <main>
        <section className="mx-auto max-w-6xl px-5 pb-20 pt-20 sm:pt-28">
          <div className="mx-auto max-w-2xl text-center">
            <h1 className="text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">Vibe trading, <span className="text-accent">done carefully.</span></h1>
            <p className="mx-auto mt-5 max-w-xl text-base text-text-muted sm:text-lg">Describe a crypto strategy in plain English. ManiQuantAI researches it, backtests it, and proves it out in paper trading — before it ever touches real capital.</p>
            <Link href="/login" className="mt-8 inline-flex items-center gap-1.5 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-bg hover:bg-accent-muted">Start for free <ArrowRight size={15} /></Link>
          </div>
        </section>

        <section id="pricing" className="border-t border-border/60 py-20">
          <div className="mx-auto max-w-6xl px-5">
            <div className="mx-auto max-w-xl text-center">
              <h2 className="text-2xl font-semibold sm:text-3xl">Simple, honest pricing</h2>
              <p className="mt-3 text-text-muted">Every plan includes live trading on MT5, Delta Exchange &amp; CoinSwitch. Tiers differ by credits and concurrent workflows.</p>
              <div className="mt-6 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
                <div className="inline-flex items-center gap-1 rounded-lg border border-border bg-bg-panel p-1">
                  <button onClick={() => setCurrency("INR")} className={`rounded-md px-4 py-1.5 text-sm font-medium ${currency === "INR" ? "bg-accent text-bg" : "text-text-muted hover:text-text"}`}>₹ INR</button>
                  <button onClick={() => setCurrency("USD")} className={`rounded-md px-4 py-1.5 text-sm font-medium ${currency === "USD" ? "bg-accent text-bg" : "text-text-muted hover:text-text"}`}>$ USD</button>
                </div>
                <div className="inline-flex items-center gap-1 rounded-lg border border-border bg-bg-panel p-1">
                  <button onClick={() => setBilling("monthly")} className={`rounded-md px-4 py-1.5 text-sm font-medium ${billing === "monthly" ? "bg-accent text-bg" : "text-text-muted hover:text-text"}`}>Monthly</button>
                  <button onClick={() => setBilling("annual")} className={`flex items-center gap-1.5 rounded-md px-4 py-1.5 text-sm font-medium ${billing === "annual" ? "bg-accent text-bg" : "text-text-muted hover:text-text"}`}>Annual <span className="rounded-full bg-bg/30 px-1.5 py-0.5 text-[10px] font-semibold">Save ~17%</span></button>
                </div>
              </div>
            </div>

            <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {PLANS.map((plan) => {
                const price = billing === "annual" ? (currency === "INR" ? plan.annualINR : plan.annualUSD) : (currency === "INR" ? plan.monthlyINR : plan.monthlyUSD);
                const isFree = price === 0;
                return (
                  <div key={plan.name} className={`relative flex flex-col rounded-xl border p-6 ${plan.tag ? "border-accent bg-accent-dim" : "border-border bg-bg-panel"}`}>
                    {plan.tag && <div className="absolute -top-3 left-1/2 -translate-x-1/2"><span className="inline-flex items-center gap-1 rounded-full bg-accent px-3 py-0.5 text-xs font-semibold text-bg"><Zap size={10} /> {plan.tag}</span></div>}
                    <div className="mb-4"><div className="text-sm font-semibold text-text-muted">{plan.name}</div><div className="mt-1.5 flex items-end gap-1"><span className="text-3xl font-bold tracking-tight">{isFree ? "Free" : `${currency === "INR" ? "₹" : "$"}${price}`}</span>{!isFree && <span className="mb-1 text-xs text-text-faint">/ mo</span>}</div>{!isFree && billing === "annual" && <div className="mt-0.5 text-xs text-text-faint">Billed {currency === "INR" ? `₹${12 * plan.annualINR}` : `$${12 * plan.annualUSD}`} / year</div>}</div>
                    <div className="mb-4 rounded-lg bg-bg-raised p-3"><div className="text-xs font-semibold">{plan.credits}</div><div className="text-xs text-text-muted">{plan.workflows}</div></div>
                    <ul className="mb-6 flex-1 space-y-2.5">{FEATURES.map((feature) => <li key={feature} className="flex items-start gap-2.5 text-sm text-text-muted"><span className="mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full bg-accent-dim text-accent"><Check size={10} /></span>{feature}</li>)}</ul>
                    <Link href="/login" className={`mt-auto rounded-lg px-4 py-2 text-center text-sm font-medium ${plan.tag ? "bg-accent text-bg hover:bg-accent-muted" : "border border-border text-text-muted hover:bg-bg-raised"}`}>{plan.cta}</Link>
                  </div>
                );
              })}
            </div>
            <p className="mt-8 text-center text-xs text-text-faint">No guaranteed returns — ever. Trading involves risk.</p>
          </div>
        </section>

        <section className="border-t border-border/60 py-20">
          <div className="mx-auto max-w-2xl px-5 text-center"><h2 className="text-2xl font-semibold sm:text-3xl">We don&apos;t promise returns. We promise rigor.</h2><p className="mt-4 text-text-muted">Every strategy is researched, backtested, paper traded, and requires human approval before live execution.</p></div>
        </section>
      </main>

      <footer className="border-t border-border/60 py-8"><div className="mx-auto max-w-6xl px-5 text-center text-xs text-text-faint">© {new Date().getFullYear()} ManiQuantAI. Not financial advice. Trading involves risk.</div></footer>
    </div>
  );
}
