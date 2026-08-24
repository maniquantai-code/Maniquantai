# ManiQuantAI MT5 Bridge

The bridge runs on the same Windows PC as the user's logged-in MetaTrader 5 terminal. It polls ManiQuantAI over HTTPS, reads MT5 market/account data, and executes only live execution jobs that have already passed the server-side approval gate.

## Setup
1. Keep MetaTrader 5 installed and logged into the desired account.
2. Install Python 3.11+.
3. In this folder run `pip install -r requirements.txt`.
4. Copy `.env.example` to `.env` and set `MANIQUANT_API_URL` and the one-time `MT5_BRIDGE_TOKEN` shown by ManiQuantAI after connecting the account.
5. Run `python agent.py` and leave it running while using ManiQuantAI.

The bridge polls `/api/mt5-bridge/jobs` every two seconds. A successful poll is the cloud heartbeat, so the dashboard can distinguish a saved MT5 account from an actually online Windows bridge.

For live execution, the cloud queues a signed/approved execution job. The bridge reads the current MT5 tick, runs `order_check`, calls `order_send`, and reports the broker retcode, order/deal IDs, fill price, and account snapshot back to ManiQuantAI. No live order is created merely by connecting the account or approving the live gate.
