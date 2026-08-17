"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Check } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { AppPreview } from "@/components/landing/AppPreview";

const PIPELINE_STEPS = [
  {
    n: "01",
    title: "Describe your strategy",
    body: "In plain English — no code, no indicator syntax. “Buy BTC when RSI drops below 30 and price is above the 200 EMA.”",
  },
  {
    n: "02",
    title: "Research & backtest",
    body: "Real computation against historical data — win rate, drawdown, Sharpe — checked against fixed rules, not vibes.",
  },
  {
    n: "03",
    title: "Paper trade first",
    body: "Every strategy runs against live market data with simulated fills before a rupee or dollar of real capital is at risk.",
  },
  {
    n: "04",
    title: "You approve, then it goes live",
    body: "A deliberate human decision, every time. No agent can skip this step for you.",
  },
];

export default function LandingPage() {
  const [checkingSession, setCheckingSession] = useState(true);
  const router = useRouter();

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) {
        router.replace("/dashboard");
      } else {
        setCheckingSession(false);
      }
    });
  }, [router]);

  if (checkingSession) return null;

  return (
    <div className="min-h-screen bg-bg text-text">
      {/* Nav */}
      <header className="sticky top-0 z-30 border-b border-border/60 bg-bg/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-dim text-accent">
              <span className="text-xs font-bold">M</span>
            </div>
            <span className="font-semibold tracking-tight">ManiQuantAI</span>
          </div>
          <nav className="flex items-center gap-4">
            <Link href="/login" className="text-sm text-text-muted hover:text-text">
              Sign in
            </Link>
            <Link
              href="/login"
              className="rounded-lg bg-accent px-3.5 py-1.5 text-sm font-medium text-bg hover:bg-accent-muted"
            >
              Get started
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-5 pb-20 pt-16 sm:pt-24">
        <div className="mx-auto max-w-2xl text-center">
          <h1 className="text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
            Vibe trading, <span className="text-accent">done carefully.</span>
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-base text-text-muted sm:text-lg">
            Describe a crypto strategy in plain English. ManiQuantAI researches it, backtests
            it, and proves it out in paper trading — before it ever touches real capital.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/login"
              className="flex items-center gap-1.5 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-bg hover:bg-accent-muted"
            >
              Start for free <ArrowRight size={15} />
            </Link>
            <Link
              href="/login"
              className="rounded-lg border border-border px-5 py-2.5 text-sm text-text-muted hover:bg-bg-panel"
            >
              Sign in
            </Link>
          </div>
        </div>

        <div className="mt-16">
          <AppPreview />
        </div>
      </section>

      {/* What is ManiQuantAI — the real, sequential pipeline */}
      <section className="border-t border-border/60 py-20">
        <div className="mx-auto max-w-6xl px-5">
          <div className="mx-auto max-w-xl text-center">
            <h2 className="text-2xl font-semibold sm:text-3xl">What is ManiQuantAI?</h2>
            <p className="mt-3 text-text-muted">
              An AI-assisted crypto trading platform built around one idea: a strategy earns
              the right to trade real money, it doesn&apos;t start with it. Every strategy
              goes through the same four steps, in order, no exceptions.
            </p>
          </div>

          <div className="mt-14 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {PIPELINE_STEPS.map((step, i) => (
              <div key={step.n} className="relative">
                <div className="mb-3 font-mono text-sm text-accent">{step.n}</div>
                <h3 className="mb-1.5 text-sm font-semibold">{step.title}</h3>
                <p className="text-sm leading-relaxed text-text-muted">{step.body}</p>
                {i < PIPELINE_STEPS.length - 1 && (
                  <div className="absolute right-[-1rem] top-2 hidden text-text-faint lg:block">
                    <ArrowRight size={14} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Honesty / stewardship section */}
      <section className="border-t border-border/60 py-20">
        <div className="mx-auto grid max-w-6xl gap-12 px-5 lg:grid-cols-2 lg:items-center">
          <div>
            <h2 className="text-2xl font-semibold sm:text-3xl">
              We don&apos;t promise returns. We promise rigor.
            </h2>
            <p className="mt-4 text-text-muted">
              No legitimate trading system can guarantee a win rate or a profit. What we
              actually build is the discipline around it — the checks that catch an
              overfit strategy before it costs you, the paper-trading window that proves a
              strategy against real market noise, and the plain-language explanations that
              tell you the truth about a result, good or bad.
            </p>
          </div>
          <ul className="space-y-4">
            {[
              "Win rate is always shown next to average win/loss size — never alone.",
              "A suspiciously good backtest gets flagged for review, not celebrated.",
              "Overtrading protections apply portfolio-wide and can't be switched off.",
              "Every credential is encrypted before it's ever stored.",
            ].map((point) => (
              <li key={point} className="flex items-start gap-3">
                <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-accent-dim text-accent">
                  <Check size={12} />
                </span>
                <span className="text-sm text-text-muted">{point}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* About */}
      <section className="border-t border-border/60 py-20">
        <div className="mx-auto max-w-2xl px-5 text-center">
          <h2 className="text-2xl font-semibold sm:text-3xl">About ManiQuantAI</h2>
          <p className="mt-4 text-text-muted">
            ManiQuantAI is built on a simple belief: the platforms that last are the ones
            that tell people the truth, especially when the truth is a loss. We&apos;d
            rather earn your trust slowly, by being straight with you every time, than
            earn your signup quickly by promising something markets can&apos;t deliver.
          </p>
        </div>
      </section>

      {/* Footer CTA */}
      <section className="border-t border-border/60 py-16">
        <div className="mx-auto max-w-xl px-5 text-center">
          <h2 className="text-xl font-semibold">Start with a strategy you already have in mind.</h2>
          <Link
            href="/login"
            className="mt-6 inline-flex items-center gap-1.5 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-bg hover:bg-accent-muted"
          >
            Get started free <ArrowRight size={15} />
          </Link>
        </div>
      </section>

      <footer className="border-t border-border/60 py-8">
        <div className="mx-auto max-w-6xl px-5 text-center text-xs text-text-faint">
          © {new Date().getFullYear()} ManiQuantAI. Not financial advice. Trading involves risk.
        </div>
      </footer>
    </div>
  );
}
