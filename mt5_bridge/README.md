# ManiQuantAI MetaTrader 5 Bridge

This bridge lets a ManiQuantAI user run automatic trading through **their own MetaTrader 5 terminal**. ManiQuantAI does not need to host an MT5 VPS.

## Architecture

```text
User's Broker Account
        |
        v
MetaTrader 5 on user's Windows PC
        |
        v
ManiQuantAI MT5 Bridge
        |
   HTTPS + opaque token
        |
        v
ManiQuantAI SaaS / API
        |
        v
Approved strategy + deterministic risk/execution gate
```

The bridge polls the SaaS for approved jobs, reads MT5 market data, and submits only server-approved execution jobs. It reports execution results and account status back to ManiQuantAI.

## What the user needs

- Windows PC
- MetaTrader 5 installed
- User logged into their broker account in MT5
- Python 3.11+
- ManiQuantAI bridge token from **Settings → Connect MT5**

A ManiQuantAI-managed VPS is **not required**.

## Setup

1. Open MetaTrader 5 and log into the desired broker account normally.
2. In ManiQuantAI, open **Settings → Connect MT5**.
3. Generate and copy the bridge token.
4. Copy `.env.example` to `.env`.
5. Set:

```env
MANIQUANT_API_URL=https://<your-maniquantai-api>
MT5_BRIDGE_TOKEN=<token-from-maniquantai>
MT5_BRIDGE_POLL_SECONDS=2
```

6. Run `START_MT5_BRIDGE.bat`.
7. Return to ManiQuantAI. The MT5 account should show **Bridge online** after its heartbeat reaches the SaaS.
8. Live trading remains gated by the ManiQuantAI approval/risk pipeline.

## Security model

- Never enter the MT5 broker password into ManiQuantAI for this connection flow.
- The bridge token is opaque and should be treated like a credential.
- Keep the token private and revoke/disconnect the MT5 account if the token is exposed.
- The cloud API queues orders; the local bridge is the component that talks to the user's MT5 terminal.
- Automatic trading should only be enabled after the strategy passes ManiQuantAI's deterministic backtest, paper-trading, and human-approval gates.

## Important limitation

The user's Windows PC and MT5 terminal must remain running for automatic execution. If the PC, MT5 terminal, AutoTrading, or bridge stops, the cloud execution gate will stop treating that bridge as online.

This is intentionally different from a hosted VPS model: **ManiQuantAI does not take custody of the user's broker session.**
