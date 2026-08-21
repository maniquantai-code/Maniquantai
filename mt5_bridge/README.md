# ManiQuantAI MT5 Bridge

The bridge runs on the same Windows PC as the user's logged-in MetaTrader 5 terminal. It is read-only: it requests candles and terminal/account status and sends them to ManiQuantAI over HTTPS. It does not place trades.

## Setup
1. Keep MetaTrader 5 installed and logged into the desired account.
2. Install Python 3.11+.
3. In this folder run `pip install -r requirements.txt`.
4. Copy `.env.example` to `.env` and set `MANIQUANT_API_URL` and the one-time `MT5_BRIDGE_TOKEN` shown by ManiQuantAI after connecting the account.
5. Run `python agent.py` and leave it running while using strategy research/backtesting.

The cloud service queues a read-only market-data request. The bridge polls for that request, reads the user's MT5 terminal, and posts the candles back. If the bridge/MT5 feed fails, the strategy pipeline uses its configured Yahoo Finance fallback.
