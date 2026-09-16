"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowDownRight, ArrowUpRight, Bot, CheckCircle2, FileUp, Globe2,
  LoaderCircle, Newspaper, RefreshCw, Search, ShieldCheck, Sparkles, TrendingUp, Upload, Zap,
} from "lucide-react";
import Link from "next/link";

type Quote = {
  symbol: string; name?: string; asset_class: string; price?: number | string | null;
  change?: number | string | null; change_percent?: number | string | null;
  currency?: string; source?: string; timestamp?: number | string | null; delayed?: boolean;
};
type Article = { title: string; description?: string; url?: string; published_at?: string | number; source?: string; symbol?: string };
const api = "/api/market-intelligence";
function n(v: unknown) { const x = Number(v); return Number.isFinite(x) ? x : null; }
function pct(v: unknown) { const x = n(v); return x === null ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}%`; }
function asArray(value: unknown): string[] { return Array.isArray(value) ? value.map(String).filter(Boolean) : []; }

export default function MarketTerminalPage() {
  const [quotes, setQuotes] = useState<Record<string, Quote[]>>({ stocks: [], crypto: [], forex: [], indexes: [] });
  const [news, setNews] = useState<Article[]>([]);
  const [provider, setProvider] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [query, setQuery] = useState("");
  const [analysis, setAnalysis] = useState<any>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fileAnalysis, setFileAnalysis] = useState<any>(null);
  const [fileAnalyzing, setFileAnalyzing] = useState(false);
  const [fileError, setFileError] = useState("");

  async function load() {
    setRefreshing(true);
    try {
      const [overviewRes, newsRes] = await Promise.all([
        fetch(`${api}/overview`, { cache: "no-store" }), fetch(`${api}/news?limit=12`, { cache: "no-store" }),
      ]);
      const overview = await overviewRes.json(); const newsPayload = await newsRes.json();
      setQuotes({ stocks: overview.stocks ?? [], crypto: overview.crypto ?? [], forex: overview.forex ?? [], indexes: overview.indexes ?? [] });
      setProvider(overview.source ?? null); setMessage(overview.message ?? overview.detail ?? ""); setNews(newsPayload.articles ?? []);
    } catch (e) { setMessage(e instanceof Error ? e.message : "Market data unavailable"); }
    finally { setLoading(false); setRefreshing(false); }
  }
  useEffect(() => { void load(); const id = window.setInterval(() => void load(), 30000); return () => window.clearInterval(id); }, []);

  const movers = useMemo(() => Object.values(quotes).flat().filter(q => q.symbol).sort((a, b) => Math.abs(n(b.change_percent) ?? 0) - Math.abs(n(a.change_percent) ?? 0)).slice(0, 10), [quotes]);
  const filteredNews = news.filter(a => `${a.title} ${a.description ?? ""}`.toLowerCase().includes(query.toLowerCase()));

  async function analyze(article: Article) {
    setAnalyzing(true); setAnalysis(null);
    try {
      const res = await fetch(`${api}/news/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ headline: article.title, body: article.description ?? "", affected_assets: article.symbol ? [article.symbol] : [] }) });
      const payload = await res.json(); setAnalysis(payload?.detail ? { error: payload.detail } : payload);
    } catch (e) { setAnalysis({ error: e instanceof Error ? e.message : "Analysis unavailable" }); }
    finally { setAnalyzing(false); }
  }

  async function analyzeFile() {
    if (!file) return;
    setFileAnalyzing(true); setFileError(""); setFileAnalysis(null);
    try {
      const form = new FormData(); form.append("file", file);
      const res = await fetch(`${api}/research-file/analyze`, { method: "POST", body: form });
      const payload = await res.json();
      if (!res.ok) throw new Error(payload?.detail || "Research analysis failed");
      setFileAnalysis(payload);
    } catch (e) { setFileError(e instanceof Error ? e.message : "Research analysis unavailable"); }
    finally { setFileAnalyzing(false); }
  }

  const synthesis = fileAnalysis?.synthesis?.parsed ?? fileAnalysis?.synthesis ?? {};
  const synthesisText = typeof synthesis === "string" ? synthesis : synthesis?.content;
  const strengths = asArray(synthesis?.strengths);
  const gaps = asArray(synthesis?.critical_gaps);
  const improvements = asArray(synthesis?.recommended_improvements);
  const actions = asArray(synthesis?.priority_actions);
  const validation = asArray(synthesis?.validation_plan);

  return (
    <main className="min-h-screen bg-bg text-text">
      <header className="sticky top-0 z-30 border-b border-border/70 bg-bg/85 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4 px-5 py-4 lg:px-8">
          <div className="flex items-center gap-3"><Link href="/dashboard" className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-bg font-black">M</Link><div><div className="font-semibold tracking-tight">ManiQuantAI</div><div className="text-[10px] uppercase tracking-[0.18em] text-text-faint">Financial Intelligence Terminal</div></div></div>
          <div className="flex items-center gap-2"><span className={`hidden items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] sm:flex ${provider ? "border-accent/30 bg-accent/10 text-accent" : "border-border bg-bg-panel text-text-faint"}`}><span className="h-1.5 w-1.5 rounded-full bg-current" />{provider ? `${provider.replaceAll("_", " ")} connected` : "Data provider unavailable"}</span><button onClick={() => void load()} className="rounded-xl border border-border bg-bg-panel p-2.5 text-text-muted hover:text-text" aria-label="Refresh"><RefreshCw size={16} className={refreshing ? "animate-spin" : ""}/></button></div>
        </div>
      </header>

      <div className="mx-auto max-w-[1500px] px-5 py-6 lg:px-8">
        <section className="grid gap-4 lg:grid-cols-[1.4fr_.6fr]">
          <div className="rounded-2xl border border-border bg-bg-panel p-6"><div className="flex items-center gap-2 text-accent"><Sparkles size={17}/><span className="text-xs font-semibold uppercase tracking-[0.18em]">AI market desk</span></div><h1 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">Understand the market before you trade it.</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-text-muted">Yahoo Finance market quotes, financial news and source-backed AI analysis in one workspace. Research is separate from execution.</p><div className="mt-5 flex max-w-xl items-center gap-2 rounded-xl border border-border bg-bg-raised px-3 py-2.5"><Search size={16} className="text-text-faint"/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search the news feed…" className="w-full bg-transparent text-sm outline-none placeholder:text-text-faint"/></div><div className="mt-3 text-[10px] text-text-faint">Quotes are provider-sourced and may be delayed by the upstream market feed.</div></div>
          <div className="rounded-2xl border border-accent/20 bg-accent/5 p-6"><div className="flex items-center gap-2 text-accent"><Bot size={18}/><span className="text-sm font-semibold">Agent desk</span></div><p className="mt-3 text-sm leading-6 text-text-muted">Research Agent → Market Agent → News Agent → Risk Agent → Execution Agent</p><div className="mt-5 flex items-center gap-2 text-xs text-text-faint"><ShieldCheck size={14} className="text-accent"/>AI research cannot bypass deterministic trading gates.</div></div>
        </section>

        {message && !provider && <div className="mt-5 rounded-xl border border-red-900/40 bg-red-950/20 p-4 text-sm text-red-200">{message}</div>}

        <section className="mt-6 rounded-2xl border border-accent/20 bg-accent/5 p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div><div className="flex items-center gap-2 text-accent"><FileUp size={17}/><h2 className="text-sm font-semibold">Upload research for an AI agent review</h2></div><p className="mt-1 max-w-3xl text-xs leading-5 text-text-muted">Share a PDF, CSV, XLSX, JSON, TXT or Markdown research file. Four specialist agents inspect the evidence, data quality, methodology and risk controls, then a lead agent turns their findings into concrete improvements.</p></div>
            <div className="flex items-center gap-2">
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-border bg-bg-panel px-4 py-2.5 text-xs font-semibold hover:border-accent/40"><Upload size={14}/>{file ? "Change file" : "Choose file"}<input type="file" className="hidden" accept=".pdf,.csv,.xlsx,.xls,.json,.txt,.md" onChange={e => { setFile(e.target.files?.[0] ?? null); setFileAnalysis(null); setFileError(""); }}/></label>
              <button disabled={!file || fileAnalyzing} onClick={() => void analyzeFile()} className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-xs font-semibold text-bg disabled:cursor-not-allowed disabled:opacity-40">{fileAnalyzing ? <LoaderCircle size={14} className="animate-spin"/> : <Bot size={14}/>}Analyze</button>
            </div>
          </div>
          {file && <div className="mt-3 flex items-center gap-2 text-[11px] text-text-muted"><CheckCircle2 size={13} className="text-accent"/>{file.name} · {(file.size / 1024 / 1024).toFixed(2)} MB · max 8 MB</div>}
          {fileError && <div className="mt-3 rounded-lg border border-red-900/40 bg-red-950/20 p-3 text-xs text-red-200">{fileError}</div>}
        </section>

        {fileAnalysis && <section className="mt-5 rounded-2xl border border-border bg-bg-panel p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><div className="flex items-center gap-2 text-accent"><Bot size={17}/><h2 className="text-sm font-semibold">ManiQuantAI research review</h2></div><p className="mt-1 text-xs text-text-faint">{fileAnalysis.file?.name} · {fileAnalysis.file?.type} · agent team: {fileAnalysis.workflow?.join(" → ")}</p></div><span className="rounded-full border border-accent/20 bg-accent/10 px-2.5 py-1 text-[10px] text-accent">Improvement report</span></div>
          {synthesisText && <pre className="mt-4 whitespace-pre-wrap rounded-xl border border-border bg-bg-raised p-4 text-xs leading-6 text-text-muted">{synthesisText}</pre>}
          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            {[["What is working", strengths], ["Critical gaps", gaps], ["Recommended improvements", improvements], ["Priority actions", actions], ["Validation plan", validation]].map(([title, items]) => (items as string[]).length ? <div key={title as string} className="rounded-xl border border-border bg-bg-raised p-4"><div className="text-xs font-semibold">{title as string}</div><ul className="mt-3 space-y-2">{(items as string[]).slice(0,8).map((item, i) => <li key={`${title}-${i}`} className="text-xs leading-5 text-text-muted">• {item}</li>)}</ul></div> : null)}
          </div>
        </section>}

        <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[["Indexes", quotes.indexes], ["Stocks", quotes.stocks], ["Crypto", quotes.crypto], ["Forex", quotes.forex]].map(([label, list]) => { const rows = list as Quote[]; return <div key={label as string} className="rounded-2xl border border-border bg-bg-panel p-4"><div className="mb-3 flex items-center justify-between"><div className="flex items-center gap-2"><Globe2 size={15} className="text-accent"/><span className="text-xs font-semibold">{label as string}</span></div><span className="text-[10px] text-text-faint">YAHOO FEED</span></div><div className="space-y-2">{(loading ? [] : rows.slice(0, 5)).map(q => { const p = n(q.change_percent); return <div key={`${label}-${q.symbol}`} className="flex items-center justify-between rounded-lg bg-bg-raised px-3 py-2"><div><div className="text-xs font-medium">{q.symbol}</div><div className="text-[10px] text-text-faint">{q.name || ""}</div></div><div className="text-right"><div className={`text-xs font-semibold ${p !== null && p >= 0 ? "text-green-400" : "text-red-400"}`}>{pct(q.change_percent)}</div><div className="text-[10px] text-text-faint">{q.price == null ? "—" : Number(q.price).toLocaleString()}</div></div></div>; })}{!loading && !rows.length && <div className="py-4 text-center text-xs text-text-faint">No Yahoo Finance data</div>}</div></div>; })}
        </section>

        <section className="mt-6 grid gap-5 xl:grid-cols-[1.15fr_.85fr]">
          <div className="rounded-2xl border border-border bg-bg-panel p-5"><div className="flex items-center justify-between"><div><div className="flex items-center gap-2"><TrendingUp size={17} className="text-accent"/><h2 className="text-sm font-semibold">Today's market movers</h2></div><p className="mt-1 text-xs text-text-faint">Largest absolute moves in the configured Yahoo Finance universe.</p></div><Zap size={16} className="text-text-faint"/></div><div className="mt-4 divide-y divide-border/70">{movers.map((q, i) => { const p = n(q.change_percent) ?? 0; return <div key={`${q.symbol}-${i}`} className="flex items-center justify-between py-3"><div className="flex items-center gap-3"><span className="w-5 text-[10px] text-text-faint">{i + 1}</span><div><div className="text-xs font-semibold">{q.symbol}</div><div className="text-[10px] text-text-faint">{q.asset_class}</div></div></div><div className="flex items-center gap-2 text-xs font-semibold">{p >= 0 ? <ArrowUpRight size={14} className="text-green-400"/> : <ArrowDownRight size={14} className="text-red-400"/>}<span className={p >= 0 ? "text-green-400" : "text-red-400"}>{pct(p)}</span></div></div>; })}{!movers.length && <div className="py-10 text-center text-xs text-text-faint">Yahoo Finance is not returning quotes right now. Refresh to retry.</div>}</div></div>
          <div className="rounded-2xl border border-border bg-bg-panel p-5"><div className="flex items-center gap-2"><Newspaper size={17} className="text-accent"/><h2 className="text-sm font-semibold">Financial news</h2></div><div className="mt-4 space-y-3">{filteredNews.slice(0, 8).map((a, i) => <button key={`${a.title}-${i}`} onClick={() => void analyze(a)} className="w-full rounded-xl border border-border bg-bg-raised p-3 text-left transition hover:border-accent/30"><div className="text-xs font-medium leading-5">{a.title}</div><div className="mt-1 text-[10px] text-text-faint">{a.source || "Yahoo Finance"}{a.published_at ? ` · ${new Date(a.published_at).toLocaleString()}` : ""}</div></button>)}{!filteredNews.length && <div className="py-10 text-center text-xs text-text-faint">No Yahoo Finance news returned.</div>}</div></div>
        </section>

        {(analyzing || analysis) && <section className="mt-5 rounded-2xl border border-accent/20 bg-accent/5 p-5"><div className="flex items-center gap-2 text-accent"><Bot size={17}/><h2 className="text-sm font-semibold">ManiQuant AI — market impact analysis</h2></div>{analyzing ? <div className="mt-4 text-xs text-text-muted">Research agents are analyzing the selected article…</div> : analysis?.error ? <div className="mt-4 text-xs text-red-300">{analysis.error}</div> : <pre className="mt-4 max-h-96 overflow-auto whitespace-pre-wrap text-xs leading-6 text-text-muted">{typeof analysis === "string" ? analysis : JSON.stringify(analysis, null, 2)}</pre>}</section>}
        <footer className="mt-8 flex flex-col gap-2 border-t border-border pt-5 text-[10px] text-text-faint sm:flex-row sm:items-center sm:justify-between"><span>Market intelligence is informational and source-backed. It is not a guaranteed-return signal.</span><span className="flex items-center gap-1"><Activity size={11}/> Execution remains behind ManiQuantAI risk gates.</span></footer>
      </div>
    </main>
  );
}
