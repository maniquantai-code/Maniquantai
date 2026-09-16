"""Market intelligence for ManiQuantAI.

Yahoo Finance is the primary market-data/news source for this workspace. The
API deliberately labels the feed as Yahoo Finance and never fabricates quotes.
The same router also exposes a document-analysis workflow for research files.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..core.llm_router import router as llm_router

api_router = APIRouter(prefix="/api/market-intelligence", tags=["market-intelligence"])

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart"
YAHOO_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"

UNIVERSE: dict[str, list[tuple[str, str]]] = {
    "indexes": [
        ("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq Composite"),
        ("^DJI", "Dow Jones"), ("^NSEI", "NIFTY 50"), ("^BSESN", "Sensex"),
    ],
    "stocks": [
        ("AAPL", "Apple"), ("NVDA", "NVIDIA"), ("MSFT", "Microsoft"),
        ("AMZN", "Amazon"), ("TSLA", "Tesla"), ("RELIANCE.NS", "Reliance Industries"),
        ("TCS.NS", "TCS"), ("HDFCBANK.NS", "HDFC Bank"),
    ],
    "crypto": [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana")],
    "forex": [("EURUSD=X", "EUR/USD"), ("GBPUSD=X", "GBP/USD"), ("USDJPY=X", "USD/JPY"), ("USDINR=X", "USD/INR")],
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def _quote_from_chart(symbol: str, fallback_name: str, payload: dict[str, Any], asset_class: str) -> dict[str, Any] | None:
    chart = payload.get("chart", {})
    results = chart.get("result") or []
    if not results:
        return None
    meta = results[0].get("meta") or {}
    price = _number(meta.get("regularMarketPrice"))
    previous = _number(meta.get("previousClose")) or _number(meta.get("chartPreviousClose"))
    change = None if price is None or previous is None else price - previous
    change_pct = None if change is None or not previous else (change / previous) * 100
    return {
        "symbol": symbol,
        "name": meta.get("longName") or meta.get("shortName") or fallback_name,
        "asset_class": asset_class,
        "price": price,
        "change": change,
        "change_percent": change_pct,
        "currency": meta.get("currency") or "",
        "timestamp": meta.get("regularMarketTime"),
        "source": "yahoo_finance",
        "delayed": bool(meta.get("exchangeDataDelayedBy", 0)),
    }


async def _yahoo_quote(client: httpx.AsyncClient, symbol: str, name: str, asset_class: str) -> dict[str, Any] | None:
    try:
        response = await client.get(
            f"{YAHOO_CHART}/{symbol}",
            params={"range": "1d", "interval": "5m", "includePrePost": "true"},
        )
        response.raise_for_status()
        return _quote_from_chart(symbol, name, response.json(), asset_class)
    except Exception:
        # Some instruments reject 5m history. A one-day interval still gives
        # the regular market price and previous close for the dashboard.
        try:
            response = await client.get(
                f"{YAHOO_CHART}/{symbol}",
                params={"range": "5d", "interval": "1d", "includePrePost": "true"},
            )
            response.raise_for_status()
            return _quote_from_chart(symbol, name, response.json(), asset_class)
        except Exception:
            return None


@api_router.get("/status")
async def provider_status():
    return {
        "status": "ready",
        "provider": "yahoo_finance",
        "feed": "Yahoo Finance chart/search endpoints",
        "live_data_policy": "Quotes are provider-backed; unavailable quotes are omitted rather than invented.",
    }


@api_router.get("/overview")
async def market_overview():
    """Return a cross-asset snapshot from Yahoo Finance."""
    result: dict[str, Any] = {"stocks": [], "crypto": [], "forex": [], "indexes": [], "source": "yahoo_finance"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=4.0), limits=httpx.Limits(max_connections=20)) as client:
        tasks: list[tuple[str, asyncio.Task]] = []
        for bucket, symbols in UNIVERSE.items():
            for symbol, name in symbols:
                tasks.append((bucket, asyncio.create_task(_yahoo_quote(client, symbol, name, bucket))))
        values = await asyncio.gather(*(task for _, task in tasks))
    for (bucket, _), quote in zip(tasks, values):
        if quote:
            result[bucket].append(quote)
    if not any(result[k] for k in ("stocks", "crypto", "forex", "indexes")):
        raise HTTPException(status_code=502, detail="Yahoo Finance returned no market quotes. Please retry shortly.")
    return result


@api_router.get("/news")
async def market_news(limit: int = Query(20, ge=1, le=100), kind: str = Query("markets")):
    """Return recent Yahoo Finance search/news results."""
    query = "stock market" if kind == "markets" else kind
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=4.0)) as client:
            response = await client.get(YAHOO_SEARCH, params={"q": query, "newsCount": limit, "quotesCount": 0})
            response.raise_for_status()
            payload = response.json()
        articles = []
        for row in (payload.get("news") or [])[:limit]:
            articles.append({
                "title": row.get("title") or "",
                "description": row.get("summary") or "",
                "url": row.get("link") or (row.get("canonicalUrl") or {}).get("url"),
                "published_at": row.get("providerPublishTime"),
                "source": row.get("publisher") or "Yahoo Finance",
                "symbol": (row.get("relatedTickers") or [None])[0],
            })
        return {"articles": articles, "source": "yahoo_finance"}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Yahoo Finance news unavailable: {exc}")


class ImpactRequest(BaseModel):
    headline: str = Field(min_length=3, max_length=500)
    body: str = Field(default="", max_length=5000)
    affected_assets: list[str] = Field(default_factory=list, max_length=30)


@api_router.post("/news/analyze")
async def analyze_news(req: ImpactRequest):
    prompt = f"""Analyze this financial news item for a market intelligence dashboard.
Do not give a buy/sell recommendation or predict a price. Separate facts from inference.
Return JSON with keys: summary, market_mechanism, potentially_affected_assets,
risks_and_uncertainties, what_to_monitor, confidence.
Headline: {req.headline}
Body: {req.body}
Affected assets already identified by data provider: {req.affected_assets}
"""
    try:
        return await llm_router.chat(
            messages=[{"role": "user", "content": prompt}],
            require_json=True, max_tokens=900, temperature=0.1, use_reasoning=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI market analysis unavailable: {exc}")


def _extract_text(filename: str, content_type: str, data: bytes) -> tuple[str, str]:
    """Convert common research formats into bounded plain text for agents."""
    lower = filename.lower()
    if lower.endswith(".pdf") or content_type == "application/pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        return text, "PDF"
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        chunks = []
        for ws in wb.worksheets[:10]:
            chunks.append(f"[Sheet: {ws.title}]")
            for row in ws.iter_rows(values_only=True):
                values = ["" if v is None else str(v) for v in row]
                if any(values):
                    chunks.append(" | ".join(values[:30]))
        return "\n".join(chunks), "XLSX"
    if lower.endswith(".csv") or content_type in {"text/csv", "application/csv"}:
        text = data.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        return "\n".join(" | ".join(row) for row in rows[:5000]), "CSV"
    if lower.endswith(".json") or "json" in content_type:
        obj = json.loads(data.decode("utf-8", errors="replace"))
        return json.dumps(obj, indent=2, ensure_ascii=False)[:60000], "JSON"
    return data.decode("utf-8", errors="replace"), "TEXT"


@api_router.post("/research-file/analyze")
async def analyze_research_file(file: UploadFile = File(...)):
    """Run parallel research/risk/data/methodology agents, then synthesize improvements."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Research files are limited to 8 MB.")
    try:
        text, file_type = _extract_text(file.filename or "research", file.content_type or "", data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read this file: {exc}")
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No readable text or table data was found in the file.")
    excerpt = text[:60000]

    base = f"""You are one specialist in ManiQuantAI's research-agent team.
Review the uploaded {file_type} research file. Do not invent facts and do not give personalized investment advice.
Identify concrete evidence from the file and clearly label assumptions.
FILE NAME: {file.filename}
FILE CONTENT:\n{excerpt}"""
    jobs = {
        "research_agent": base + "\nFocus on the thesis, evidence, missing evidence, and research quality. Return concise JSON.",
        "data_agent": base + "\nFocus on data sources, sample size, missing values, look-ahead/survivorship bias, reproducibility, and data-quality issues. Return concise JSON.",
        "risk_agent": base + "\nFocus on risk controls, drawdown, position sizing, liquidity, costs, regime risk, and failure scenarios. Return concise JSON.",
        "strategy_agent": base + "\nFocus on whether the methodology/strategy is precise, testable, deterministic, and operational. Identify ambiguous rules. Return concise JSON.",
    }

    async def run_agent(name: str, prompt: str) -> tuple[str, dict[str, Any]]:
        result = await llm_router.chat(
            messages=[{"role": "user", "content": prompt}],
            require_json=True, max_tokens=850, temperature=0.1, use_reasoning=False,
        )
        return name, result

    try:
        results = await asyncio.gather(*(run_agent(name, prompt) for name, prompt in jobs.items()))
        agent_outputs = dict(results)
        synthesis_prompt = """You are the lead research agent for ManiQuantAI. Synthesize the specialist reviews below.
Return JSON with exactly these keys:
summary, strengths, critical_gaps, recommended_improvements, priority_actions, validation_plan, questions_for_user, confidence.
Use arrays for all keys except summary and confidence. Do not recommend buying/selling any asset. Focus on making the uploaded work more rigorous, reproducible, testable, and risk-aware.
SPECIALIST REVIEWS:\n""" + json.dumps(agent_outputs, ensure_ascii=False)[:30000]
        synthesis = await llm_router.chat(
            messages=[{"role": "user", "content": synthesis_prompt}],
            require_json=True, max_tokens=1400, temperature=0.1, use_reasoning=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Research agents unavailable: {exc}")

    return {
        "file": {"name": file.filename, "type": file_type, "bytes": len(data)},
        "agents": agent_outputs,
        "synthesis": synthesis,
        "workflow": ["Research Agent", "Data Agent", "Risk Agent", "Strategy Agent", "Lead Synthesis"],
    }
