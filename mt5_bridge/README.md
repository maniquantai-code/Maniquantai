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
ManiQuantAI MT5 Bridge Login
        |
   HTTPS + opaque token
        |
        v
ManiQuantAI SaaS / API
        |
        v
Approved strategy + deterministic risk/execution gate
```

## What the user needs

- Windows PC
- MetaTrader 5 installed
- User logged into their broker account in MT5
- Python 3.11+
- ManiQuantAI bridge token from **Settings → Connect MT5**

A ManiQuantAI-managed VPS is **not required**.

## Token lifecycle

1. Sign in to ManiQuantAI and open **Settings → Connect MT5**.
2. Click **Generate token**.
3. Copy the token. The full token is returned only to the authenticated ManiQuantAI session; Supabase stores only its hash.
4. Start `START_MT5_BRIDGE.bat`.
5. A Windows login screen appears. Paste the token and click **Connect to MT5**.
6. The bridge validates the token, initializes the already-open MT5 terminal, and starts its heartbeat/job polling.
7. If the token is lost or exposed, return to **Settings → Connect MT5 → Revoke**. The old token stops working immediately.
8. Use **Refresh token** to rotate the credential. The old token is invalidated and a new token is displayed once.

Tokens are time-limited. The current cloud policy issues them for 30 days. Refresh before expiry if the bridge should remain authorized.

## Setup

1. Open MetaTrader 5 and log into the desired broker account normally.
2. In ManiQuantAI, open **Settings → Connect MT5** and generate a token.
3. Start `START_MT5_BRIDGE.bat`.
4. Paste the token into the Windows bridge login screen.
5. Keep MT5, AutoTrading, and the bridge running while automatic trading is enabled.
6. Return to ManiQuantAI. The MT5 account should show **Bridge online** after its heartbeat reaches the SaaS.
7. Live trading remains gated by the ManiQuantAI approval/risk pipeline.

## Security model

- Never enter the MT5 broker password into ManiQuantAI for this bridge flow.
- The bridge token is an opaque credential and should be treated like a password.
- The full token is not stored in Supabase; only a SHA-256 hash (with the server-side bridge pepper) is stored.
- Revoke immediately if the token is exposed.
- Refresh rotates the token and invalidates the previous token.
- The cloud API queues orders; the local bridge is the component that talks to the user's MT5 terminal.
- Automatic trading should only be enabled after the strategy passes ManiQuantAI's deterministic backtest, paper-trading, and human-approval gates.

## Important limitation

The user's Windows PC and MT5 terminal must remain running for automatic execution. If the PC, MT5 terminal, AutoTrading, or bridge stops, the cloud execution gate will stop treating that bridge as online.

This is intentionally different from a hosted VPS model: **ManiQuantAI does not take custody of the user's broker session.**
