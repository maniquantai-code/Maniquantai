-- Allow an MT5 bridge connector record to exist before the user's terminal
-- has supplied encrypted account/credential payload data.
alter table public.broker_accounts
  alter column encrypted_payload drop not null;
