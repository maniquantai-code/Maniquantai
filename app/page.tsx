"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight, BarChart3, Check, ChevronRight, Cpu, FlaskConical,
  LockKeyhole, Play, Quote, ShieldCheck, Sparkles, Target, UserCheck, Zap
} from "lucide-react";
import { supabase } from "@/lib/supabase";

const PLANS = [
  { name:"Free", monthlyINR:0, monthlyUSD:0, annualINR:0, annualUSD:0, tag:null, cta:"Start free", credits:"80 credits / mo", workflows:"1 active workflow" },
  { name:"Starter", monthlyINR:299, monthlyUSD:20, annualINR:249, annualUSD:17, tag:null, cta:"Get started", credits:"500 credits / mo", workflows:"3 active workflows" },
  { name:"Pro", monthlyINR:699, monthlyUSD:49, annualINR:583, annualUSD:41, tag:"Most popular", cta:"Go Pro", credits:"1,500 credits / mo", workflows:"10 active workflows" },
  { name:"Elite", monthlyINR:1499, monthlyUSD:99, annualINR:1249, annualUSD:83, tag:null, cta:"Go Elite", credits:"4,000 credits / mo", workflows:"Unlimited workflows" }
];

const FEATURES = [
  "MT5, Delta Exchange & CoinSwitch",
  "Live trade execution",
  "Backtest & paper trading",
  "Capital preservation guardrails"
];

const STEPS = [
  { icon:Sparkles, n:"01", t:"Describe", d:"Describe your crypto trading idea in plain English — no code required." },
  { icon:FlaskConical, n:"02", t:"Research & backtest", d:"Research the setup, compile it into a deterministic strategy, and test it historically." },
  { icon:BarChart3, n:"03", t:"Paper trade", d:"Validate behavior in simulated markets before exposing real capital." },
  { icon:UserCheck, n:"04", t:"Approve", d:"Live execution requires explicit human approval and safety gates." }
];

const REVIEWS = [
  ["The workflow makes the important distinction between having an idea and having evidence.","Early-access trader","Product feedback"],
  ["I like the paper-trading gate. It makes the product feel more like a research cockpit than a signal box.","Beta user","Strategy testing"],
  ["The focus on process and guardrails is what stood out to me during early testing.","Community tester","Early feedback"]
];

export default function LandingPage() {
  const [checking,setChecking] = useState(true);
  const [currency,setCurrency] = useState<"INR"|"USD">("INR");
  const [billing,setBilling] = useState<"monthly"|"annual">("monthly");
  const router = useRouter();

  useEffect(() => {
    supabase.auth.getSession().then(({data}) => {
      if (data.session) router.replace("/dashboard");
      else setChecking(false);
    });
  }, [router]);

  if (checking) return null;

  return (
    <div className="min-h-screen overflow-hidden bg-bg text-text">
      <header className="sticky top-0 z-40 border-b border-border/60 bg-bg/75 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 lg:px-8">
          <Link href="#top" className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent-dim text-accent font-black">M</span>
            <span className="font-semibold tracking-tight">ManiQuantAI</span>
          </Link>
          <nav className="hidden gap-6 md:flex">
            <a href="#about" className="text-sm text-text-muted hover:text-text">About</a>
            <a href="#how" className="text-sm text-text-muted hover:text-text">How it works</a>
            <a href="#reviews" className="text-sm text-text-muted hover:text-text">Reviews</a>
            <a href="#pricing" className="text-sm text-text-muted hover:text-text">Pricing</a>
          </nav>
          <div className="flex items-center gap-3">
            <Link href="/login" className="hidden text-sm text-text-muted hover:text-text sm:block">Sign in</Link>
            <Link href="/login" className="group inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-bg hover:bg-accent-muted">
              Get started <ArrowRight size={14}/>
            </Link>
          </div>
        </div>
      </header>

      <main id="top">
        <section className="relative isolate border-b border-border/60">
          <div className="hero-grid absolute inset-0 -z-20 opacity-60"/>
          <div className="absolute left-1/2 top-0 -z-10 h-[520px] w-[900px] -translate-x-1/2 rounded-full bg-accent/10 blur-[130px]"/>
          <div className="mx-auto grid max-w-7xl items-center gap-14 px-5 pb-24 pt-20 lg:grid-cols-[1.05fr_.95fr] lg:px-8 lg:pb-28 lg:pt-28">
            <div className="animate-fade-up">
              <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-accent/20 bg-accent-dim px-3 py-1.5 text-xs font-medium text-accent">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent"/>
                AI-powered trading research & execution
              </div>
              <h1 className="max-w-3xl text-5xl font-semibold leading-[1.03] tracking-[-0.04em] sm:text-6xl lg:text-7xl">
                Turn ideas into <span className="text-gradient">validated strategies.</span>
              </h1>
              <p className="mt-6 max-w-2xl text-base leading-7 text-text-muted sm:text-lg">
                Describe a crypto strategy in plain English. ManiQuantAI researches it, backtests it, paper trades it, and waits for your approval before real capital is put at risk.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Link href="/login" className="group inline-flex justify-center items-center gap-2 rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-bg hover:-translate-y-1 hover:bg-accent-muted">
                  Start for free <ArrowRight size={16}/>
                </Link>
                <a href="#how" className="inline-flex justify-center items-center gap-2 rounded-xl border border-border bg-bg-panel px-5 py-3 text-sm font-medium hover:-translate-y-1">
                  <Play size={15}/>See how it works
                </a>
              </div>
              <div className="mt-9 flex flex-wrap gap-x-6 gap-y-3 text-xs text-text-faint">
                <span className="inline-flex items-center gap-1.5"><ShieldCheck size={14} className="text-accent"/>Human approval required</span>
                <span className="inline-flex items-center gap-1.5"><LockKeyhole size={14} className="text-accent"/>Safety-first execution</span>
                <span className="inline-flex items-center gap-1.5"><Zap size={14} className="text-accent"/>No guaranteed returns</span>
              </div>
            </div>

            <div className="relative animate-float">
              <div className="absolute -inset-5 rounded-[2rem] bg-accent/5 blur-2xl"/>
              <div className="relative rounded-[1.5rem] border border-border bg-bg-panel/90 shadow-2xl backdrop-blur-xl">
                <div className="flex items-center justify-between border-b border-border px-5 py-4">
                  <div><div className="text-xs text-text-faint">Strategy workspace</div><div className="mt-1 font-medium">BTC momentum / 1H</div></div>
                  <span className="rounded-full bg-accent-dim px-2.5 py-1 text-[10px] font-semibold text-accent">PAPER MODE</span>
                </div>
                <div className="grid gap-4 p-5 sm:grid-cols-[1.2fr_.8fr]">
                  <div className="rounded-xl border border-border bg-bg-raised p-4">
                    <div className="mb-4 flex justify-between text-xs"><span className="text-text-muted">Equity curve</span><span className="text-accent">validated</span></div>
                    <div className="flex h-40 items-end gap-1.5">
                      {[32,38,35,48,43,55,51,63,60,72,68,78,74,88,82,94].map((h,i)=>
                        <div key={i} className="bar-animate flex-1 rounded-t-sm bg-accent/70" style={{height:`${h}%`,animationDelay:`${i*55}ms`}}/>
                      )}
                    </div>
                    <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                      <div><b className="text-sm">+18.4%</b><div className="text-[10px] text-text-faint">Test return</div></div>
                      <div><b className="text-sm">-7.2%</b><div className="text-[10px] text-text-faint">Max drawdown</div></div>
                      <div><b className="text-sm">1.84</b><div className="text-[10px] text-text-faint">Sharpe</div></div>
                    </div>
                  </div>
                  <div className="space-y-3">
                    {[
                      ["Research","Complete",Sparkles],
                      ["Backtest","Passed",FlaskConical],
                      ["Paper trade","Running",BarChart3],
                      ["Approval","Required",UserCheck]
                    ].map(([l,s,I]) => {
                      const Icon = I as typeof Sparkles;
                      return <div key={l as string} className="rounded-xl border border-border bg-bg-raised p-3">
                        <div className="flex items-center gap-2"><Icon size={14} className="text-accent"/><span className="text-xs font-medium">{l as string}</span></div>
                        <div className="mt-2 text-[10px] text-text-faint">{s as string}</div>
                      </div>
                    })}
                  </div>
                </div>
                <div className="flex justify-between border-t border-border px-5 py-4 text-[11px]">
                  <span className="text-text-faint">Execution gate: human approval</span>
                  <span className="text-accent">Capital stewardship</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="about" className="border-b border-border/60 py-24">
          <div className="mx-auto grid max-w-7xl gap-12 px-5 lg:grid-cols-[.8fr_1.2fr] lg:px-8">
            <div>
              <div className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-accent">About ManiQuantAI</div>
              <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">A trading copilot built around <span className="text-gradient">discipline.</span></h2>
              <p className="mt-5 leading-7 text-text-muted">ManiQuantAI helps traders move from a hypothesis to evidence, paper validation, and deliberate execution — rather than jumping straight from prompt to live order.</p>
            </div>
            <div className="grid gap-5 sm:grid-cols-2">
              {[
                [Target,"Research before execution","Turn a trading hypothesis into evidence before treating it as executable."],
                [ShieldCheck,"Capital stewardship","Explicit gates and human approval help keep real capital behind a deliberate decision."],
                [Cpu,"Agentic workflow","Specialized agents support research, backtesting, monitoring, learning, incidents, and execution."],
                [LockKeyhole,"No black-box promises","Trading is risky. ManiQuantAI does not make guaranteed-return claims."]
              ].map(([I,t,d]) => {
                const Icon = I as typeof Target;
                return <div key={t as string} className="rounded-2xl border border-border bg-bg-panel p-6 transition hover:-translate-y-1 hover:border-accent/30">
                  <Icon size={22} className="mb-5 text-accent"/><h3 className="font-semibold">{t as string}</h3>
                  <p className="mt-2 text-sm leading-6 text-text-muted">{d as string}</p>
                </div>
              })}
            </div>
          </div>
        </section>

        <section id="how" className="border-b border-border/60 py-24">
          <div className="mx-auto max-w-7xl px-5 lg:px-8">
            <div className="mx-auto max-w-2xl text-center">
              <div className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-accent">The workflow</div>
              <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">From prompt to proof — not hype.</h2>
              <p className="mt-4 text-text-muted">Research, deterministic validation, paper trading, and live execution are separated by deliberate gates.</p>
            </div>
            <div className="mt-14 grid gap-4 md:grid-cols-4">
              {STEPS.map((s,i) => <div key={s.n} className="group relative rounded-2xl border border-border bg-bg-panel p-6 transition duration-300 hover:-translate-y-2 hover:border-accent/30">
                {i<3 && <ChevronRight className="absolute -right-4 top-1/2 z-10 hidden -translate-y-1/2 text-text-faint md:block" size={18}/>}
                <div className="flex justify-between"><s.icon size={21} className="text-accent"/><span className="font-mono text-xs text-text-faint">{s.n}</span></div>
                <h3 className="mt-7 font-semibold">{s.t}</h3><p className="mt-2 text-sm leading-6 text-text-muted">{s.d}</p>
              </div>)}
            </div>
          </div>
        </section>

        <section id="reviews" className="border-b border-border/60 py-24">
          <div className="mx-auto max-w-7xl px-5 lg:px-8">
            <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
              <div><div className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-accent">Early feedback</div><h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">Built with traders, not fabricated testimonials.</h2></div>
              <p className="max-w-md text-sm leading-6 text-text-muted">Representative early-access feedback is shown without invented performance claims.</p>
            </div>
            <div className="mt-12 grid gap-5 md:grid-cols-3">
              {REVIEWS.map(([q,n,r]) => <article key={n as string} className="rounded-2xl border border-border bg-bg-panel p-6 transition hover:-translate-y-1">
                <Quote size={22} className="text-accent"/><p className="mt-5 text-sm leading-6 text-text-muted">“{q as string}”</p>
                <div className="mt-7 border-t border-border pt-5"><div className="text-sm font-semibold">{n as string}</div><div className="mt-1 text-xs text-text-faint">{r as string}</div></div>
              </article>)}
            </div>
          </div>
        </section>

        <section id="pricing" className="border-b border-border/60 py-24">
          <div className="mx-auto max-w-7xl px-5 lg:px-8">
            <div className="mx-auto max-w-2xl text-center">
              <div className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-accent">Pricing</div>
              <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">Simple, honest pricing.</h2>
              <p className="mt-4 text-text-muted">Choose your credit capacity and workflow limits. No plan promises profits.</p>
              <div className="mt-7 flex flex-col items-center justify-center gap-3 sm:flex-row">
                <div className="inline-flex rounded-xl border border-border bg-bg-panel p-1">
                  <button onClick={()=>setCurrency("INR")} className={`rounded-lg px-4 py-1.5 text-sm font-medium ${currency==="INR"?"bg-accent text-bg":"text-text-muted"}`}>₹ INR</button>
                  <button onClick={()=>setCurrency("USD")} className={`rounded-lg px-4 py-1.5 text-sm font-medium ${currency==="USD"?"bg-accent text-bg":"text-text-muted"}`}>$ USD</button>
                </div>
                <div className="inline-flex rounded-xl border border-border bg-bg-panel p-1">
                  <button onClick={()=>setBilling("monthly")} className={`rounded-lg px-4 py-1.5 text-sm font-medium ${billing==="monthly"?"bg-accent text-bg":"text-text-muted"}`}>Monthly</button>
                  <button onClick={()=>setBilling("annual")} className={`rounded-lg px-4 py-1.5 text-sm font-medium ${billing==="annual"?"bg-accent text-bg":"text-text-muted"}`}>Annual <span className="ml-1 text-[10px]">Save ~17%</span></button>
                </div>
              </div>
            </div>

            <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {PLANS.map(p => {
                const price = billing==="annual" ? (currency==="INR"?p.annualINR:p.annualUSD) : (currency==="INR"?p.monthlyINR:p.monthlyUSD);
                const free = price===0;
                return <div key={p.name} className={`relative flex flex-col rounded-2xl border p-6 transition hover:-translate-y-2 ${p.tag?"border-accent bg-accent-dim":"border-border bg-bg-panel"}`}>
                  {p.tag && <div className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-accent px-3 py-1 text-xs font-semibold text-bg"><Zap size={10} className="mr-1 inline"/>{p.tag}</div>}
                  <div className="text-sm font-semibold text-text-muted">{p.name}</div>
                  <div className="mt-2 text-3xl font-bold">{free?"Free":`${currency==="INR"?"₹":"$"}${price}`} {!free&&<span className="text-xs font-normal text-text-faint">/ mo</span>}</div>
                  {!free&&billing==="annual"&&<div className="mt-1 text-xs text-text-faint">Billed {currency==="INR"?`₹${12*p.annualINR}`:`$${12*p.annualUSD}`} / year</div>}
                  <div className="my-5 rounded-xl bg-bg-raised p-3"><b className="text-xs">{p.credits}</b><div className="text-xs text-text-muted">{p.workflows}</div></div>
                  <ul className="mb-7 flex-1 space-y-2.5">{FEATURES.map(f=><li key={f} className="flex gap-2 text-sm text-text-muted"><span className="mt-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-accent-dim text-accent"><Check size={10}/></span>{f}</li>)}</ul>
                  <Link href="/login" className={`rounded-xl px-4 py-2.5 text-center text-sm font-semibold ${p.tag?"bg-accent text-bg":"border border-border text-text-muted hover:bg-bg-raised"}`}>{p.cta}</Link>
                </div>
              })}
            </div>
            <p className="mt-9 text-center text-xs text-text-faint">No guaranteed returns — ever. Trading involves risk. ManiQuantAI is not financial advice.</p>
          </div>
        </section>

        <section className="relative overflow-hidden py-24">
          <div className="absolute left-1/2 top-1/2 -z-10 h-72 w-72 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent/10 blur-[100px]"/>
          <div className="mx-auto max-w-4xl px-5 text-center lg:px-8">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-dim text-accent"><Sparkles size={22}/></div>
            <h2 className="mt-6 text-3xl font-semibold tracking-tight sm:text-5xl">Trade with a process you can understand.</h2>
            <p className="mx-auto mt-5 max-w-2xl text-text-muted">Start with an idea. Demand evidence. Paper trade. Approve deliberately.</p>
            <Link href="/login" className="group mt-8 inline-flex items-center gap-2 rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-bg hover:-translate-y-1">Build your first strategy <ArrowRight size={16}/></Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-border/60 py-9">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 text-center text-xs text-text-faint sm:flex-row sm:justify-between lg:px-8">
          <span>© {new Date().getFullYear()} ManiQuantAI. Not financial advice. Trading involves risk.</span>
          <div className="flex justify-center gap-5"><a href="#about">About</a><a href="#pricing">Pricing</a><Link href="/login">Sign in</Link></div>
        </div>
      </footer>
    </div>
  );
}
