-- Multi-broker market-data connectors.
-- Secrets remain in encrypted_payload; the UI never receives them.
alter table public.broker_accounts
  add column if not exists is_primary boolean not null default false;

create index if not exists broker_accounts_user_primary_idx
  on public.broker_accounts(user_id, is_primary);

create unique index if not exists broker_accounts_one_primary_per_user_idx
  on public.broker_accounts(user_id)
  where is_primary = true;

-- Existing MT5 accounts remain valid. New connector_type values such as
-- broker_api are intentionally supported by the existing text column.
