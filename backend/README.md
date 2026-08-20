# ManiQuantAI Backend

FastAPI backend with intelligent LLM routing across free OpenRouter models.

## LLM Router

The router keeps trading workflows alive 24/7 by:
1. Trying models in priority order (Nemotron Ultra → Nemotron Lightning → Gemma 4)
2. Circuit-breaking failed models (marks unavailable for 120s after 3 consecutive failures)
3. Auto-recovering — resets failure count after cooldown
4. Background health monitor pings every model every 60s

### Model priority

| Priority | Model | Size | Reasoning |
|---|---|---|---|
| 1 | `openai/gpt-oss-20b:free` | 20B | ✅ |
| 2 | `nvidia/nemotron-3-ultra-550b-a55b:free` | 550B | ✅ |
| 3 | `nvidia/nemotron-3.5-lightning:free` | — | ✅ |
| 4 | `google/gemma-4-26b-a4b-it:free` | 26B | ❌ |
| Future | `anthropic/claude-sonnet-4-6` | — | ✅ |

## Setup

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Fill in SUPABASE_SERVICE_ROLE_KEY and FERNET_KEY
uvicorn backend.main:app --reload --port 8000
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | App health |
| GET | `/api/llm/health` | All model statuses |
| POST | `/api/llm/test` | Test the router |
| POST | `/api/llm/chat` | Raw LLM chat |
| POST | `/api/chat` | Strategy chat (frontend) |
| GET | `/api/strategies` | List strategies |
| POST | `/api/strategies` | Create strategy |
| GET | `/api/wallet` | Credit balance |
| GET | `/api/broker-accounts` | List connections |
| POST | `/api/broker-accounts/mt5` | Connect MT5 |
| DELETE | `/api/broker-accounts/{id}` | Disconnect |
