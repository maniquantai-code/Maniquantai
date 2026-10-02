-- Allow multiple broker/API connections per user while preserving one connector/name pair.
alter table public.broker_accounts
  drop constraint if exists broker_accounts_user_id_key;

create unique index if not exists broker_accounts_user_connector_idx
  on public.broker_accounts(user_id, connector_type, connector_name);

comment on table public.broker_accounts is
  'Encrypted trading connector credentials. Supports MT5 and generic HTTPS broker APIs; plaintext API secrets must never be stored.';
