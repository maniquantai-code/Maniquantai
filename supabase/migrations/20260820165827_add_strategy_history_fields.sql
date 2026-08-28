alter table public.strategies
  add column if not exists strategy_id uuid unique default gen_random_uuid(),
  add column if not exists name text,
  add column if not exists raw_strategy_text text,
  add column if not exists fast_track boolean not null default false,
  add column if not exists heightened_monitoring_day integer,
  add column if not exists heightened_monitoring_total integer,
  add column if not exists updated_at timestamptz not null default now();

update public.strategies
set strategy_id = coalesce(strategy_id, id),
    name = coalesce(name, 'Untitled Strategy'),
    updated_at = coalesce(updated_at, created_at, now())
where strategy_id is null or name is null;

create index if not exists strategies_user_created_idx on public.strategies (user_id, created_at desc);
create index if not exists strategies_strategy_id_idx on public.strategies (strategy_id);
