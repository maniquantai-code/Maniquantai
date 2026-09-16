# ManiQuantAI 2.0 — Financial Intelligence + Agentic Trading

## Product model

ManiQuantAI is designed as a mini AI investment/trading team:

- Market Intelligence Agent — prices, movers and cross-asset context
- News Agent — financial news ingestion and event extraction
- Research Agent — company/sector/market research
- Strategy Agent — natural-language idea to deterministic specification
- Backtest Agent — deterministic historical testing
- Risk Agent — independent capital and exposure controls
- Portfolio Agent — positions, watchlists and strategy state
- Execution Agent — broker/MT5 order workflow
- Monitoring Agent — heartbeats, fills, rejects and incidents

The LLM can research and explain. It cannot bypass the deterministic risk or execution gates.

## Financial intelligence terminal

`/market` provides a Bloomberg-style foundation for retail and professional users:

- cross-asset market overview
- stocks, crypto, forex and indexes
- top movers in the configured universe
- financial news
- source-backed AI news impact analysis

The backend is provider-backed and never fabricates live market data. Configure:

- `TRADING_ECONOMICS_API_KEY` for broad markets, financial news and economic data
- `TWELVE_DATA_API_KEY` for multi-asset market data

Provider licensing and redistribution rights must be confirmed before commercial distribution of any feed.

## MT5 realtime bridge

`mt5-bridge/realtime_agent.py` is the realtime execution worker. It runs on the user's Windows machine beside MT5.

Key properties:

1. Persistent HTTP connection instead of creating a client for every request.
2. Default 500 ms deterministic strategy scan loop.
3. Separate 2 second account/bridge heartbeat.
4. MT5 reconnect handling when terminal/account state disappears.
5. Completed-candle evaluation to avoid repeated intrabar signals.
6. Signal-key deduplication.
7. `order_check` before `order_send`.
8. Post-order position/account verification.
9. Server remains the authority for approval and execution authorization.
10. LLM output is never passed directly to MT5.

Start with `START_REALTIME_BRIDGE.bat` after configuring `MANIQUANT_API` and `MT5_BRIDGE_TOKEN`.

## Live trading architecture

```text
Market Data + News
        |
        v
  AI Research Team
        |
        v
 Strategy Specification
        |
        v
 Deterministic Compiler
        |
        +---- Backtest
        +---- Indicator Verification
        +---- Robustness Checks
        |
        v
    Risk Engine
        |
        v
 Human Approval / Automation Policy
        |
        v
   Live Execution Gate
        |
        v
 Realtime MT5 Bridge
        |
        v
   Broker / MT5
        |
        v
Execution + Audit Logs
```

## Important production requirements

Before enabling broad automatic trading, add/verify:

- per-user risk limits
- max daily loss and max drawdown stops
- stale-price and spread checks
- duplicate-order/idempotency keys
- broker rejection handling
- order/fill reconciliation
- bridge offline kill behavior
- jurisdiction-specific broker/API controls
- complete audit logs
- market-data licensing and redistribution compliance
