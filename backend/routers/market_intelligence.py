"""Market intelligence layer for ManiQuantAI.

Provider-backed only: the API never invents live market data. Configure
TRADING_ECONOMICS_API_KEY and/or TWELVE_DATA_API_KEY in the backend.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.llm_router import router as llm_router

api_router = APIRouter(prefix="/api/market-intelligence", tags=["market-intelligence"])

TE_KEY = os.getenv("TRADING_ECONOMICS_API_KEY", "").strip()
TD_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
TE_BASE = "https://api.tradingeconomics.com"
TD_BASE = "https://api.twelvedata.com"


def _pick(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
        lower = name.lower()
        for key, value in row.items():
            if str(key).lower() == lower and value not in (None, ""):
                return value
    return default


def _normalize_quote(row: dict[str, Any], asset_class: str) -> dict[str, Any]:
    last = _pick(row, "last", "price", "close", "closePrice")
    change = _pick(row, "dailyChange", "change", "changePrice")
    pct = _pick(row, "dailyPercentChange", "percentChange", "changePercent", "percent")
    return {
        "symbol": _pick(row, "symbol", "ticker", "code", default=""),
        "name": _pick(row, "name", "Name", "description", default=""),
        "asset_class": asset_class,
        "price": last,
        "change": change,
        "change_percent": pct,
        "currency": _pick(row, "currency", "Currency", default=""),
        "timestamp": _pick(row, "date", "datetime", "timestamp", "updated", default=None),
        "source": "trading_economics",
    }


async def _te_get(path: str, params: dict[str, Any] | None = None) -> Any:
    if not TE_KEY:
        return []
    query = {"c": TE_KEY, **(params or {})}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{TE_BASE}{path}", params=query)
        response.raise_for_status()
        return response.json()


async def _td_get(path: str, params: dict[str, Any] | None = None) -> Any:
    if not TD_KEY:
        return {}
    query = {"apikey": TD_KEY, **(params or {})}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{TD_BASE}{path}", params=query)
        response.raise_for_status()
        return response.json()


@api_router.get("/status")
async def provider_status():
    return {
        "status": "ready" if (TE_KEY or TD_KEY) else "not_configured",
        "providers": {
            "trading_economics": bool(TE_KEY),
            "twelve_data": bool(TD_KEY),
        },
        "live_data_policy": "No provider data means no live quote is displayed.",
    }


@api_router.get("/overview")
async def market_overview():
    """Return normalized cross-asset market snapshots from configured providers."""
    result: dict[str, Any] = {"stocks": [], "crypto": [], "forex": [], "indexes": [], "source": None}
    if TE_KEY:
        endpoints = [
            ("stocks", "/markets/stock"),
            ("crypto", "/markets/crypto"),
            ("forex", "/markets/currency"),
            ("indexes", "/markets/index"),
        ]
        try:
            for bucket, endpoint in endpoints:
                payload = await _te_get(endpoint)
                rows = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
                result[bucket] = [_normalize_quote(r, bucket) for r in rows if isinstance(r, dict)]
            result["source"] = "trading_economics"
        except Exception as exc:
            if not TD_KEY:
                raise HTTPException(status_code=502, detail=f"Market provider error: {exc}")
    if not result["source"] and TD_KEY:
        symbols = {
            "stocks": "AAPL,NVDA,MSFT,AMZN,TSLA",
            "crypto": "BTC/USD,ETH/USD,SOL/USD",
            "forex": "EUR/USD,GBP/USD,USD/JPY,USD/INR",
            "indexes": "SPX,NDX",
        }
        for bucket, symbol_list in symbols.items():
            payload = await _td_get("/quote", {"symbol": symbol_list})
            rows = payload if isinstance(payload, dict) else {}
            if "symbol" in rows:
                rows = {str(rows.get("symbol")): rows}
            for symbol, row in rows.items():
                if isinstance(row, dict):
                    result[bucket].append({
                        "symbol": symbol,
                        "name": row.get("name", symbol),
                        "asset_class": bucket,
                        "price": row.get("close") or row.get("price"),
                        "change": row.get("change"),
                        "change_percent": row.get("percent_change"),
                        "currency": row.get("currency", ""),
                        "timestamp": row.get("datetime"),
                        "source": "twelve_data",
                    })
        result["source"] = "twelve_data"
    if not result["source"]:
        result["message"] = "Configure TRADING_ECONOMICS_API_KEY or TWELVE_DATA_API_KEY to enable live market data."
    return result


@api_router.get("/news")
async def market_news(limit: int = Query(20, ge=1, le=100), kind: str = Query("markets")):
    if not TE_KEY:
        return {"articles": [], "source": None, "message": "Configure TRADING_ECONOMICS_API_KEY to enable financial news."}
    try:
        payload = await _te_get("/news", {"type": kind})
        rows = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
        articles = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            articles.append({
                "title": _pick(row, "title", "Title", default=""),
                "description": _pick(row, "description", "Description", "content", default=""),
                "url": _pick(row, "url", "URL", default=None),
                "published_at": _pick(row, "date", "Date", "published", default=None),
                "source": _pick(row, "source", "Source", default="Trading Economics"),
                "symbol": _pick(row, "symbol", "ticker", "Ticker", default=None),
            })
        return {"articles": articles, "source": "trading_economics"}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"News provider error: {exc}")


class ImpactRequest(BaseModel):
    headline: str = Field(min_length=3, max_length=500)
    body: str = Field(default="", max_length=5000)
    affected_assets: list[str] = Field(default_factory=list, max_length=30)


@api_router.post("/news/analyze")
async def analyze_news(req: ImpactRequest):
    """Ask the existing model router for a source-grounded market-impact explanation."""
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
            require_json=True,
            max_tokens=900,
            temperature=0.1,
            use_reasoning=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI market analysis unavailable: {exc}")
