-- ManiQuantAI execution certificate + replay protection
-- The certificate is bound to the exact live strategy snapshot. The bridge
-- presents it with every live signal; the database re-checks the snapshot
-- before queueing and consumes a unique execution nonce.

create extension if not exists pgcrypto;

create table if not exists public.execution_certificates (
  id uuid primary key default gen_random_uuid(),
  strategy_id uuid not null references public.strategies(strategy_id) on delete cascade,
  user_id uuid not null,
  snapshot_hash text not null check (snapshot_hash ~ '^[0-9a-f]{64}$'),
  certificate_hash text not null check (certificate_hash ~ '^[0-9a-f]{64}$'),
  issued_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz,
  last_heartbeat_at timestamptz,
  unique(strategy_id),
  unique(certificate_hash)
);

create index if not exists execution_certificates_user_idx
  on public.execution_certificates(user_id, expires_at);

alter table public.execution_certificates enable row level security;
revoke all on public.execution_certificates from anon;
revoke all on public.execution_certificates from authenticated;

create table if not exists public.execution_replays (
  nonce uuid primary key,
  strategy_id uuid not null references public.strategies(strategy_id) on delete cascade,
  user_id uuid not null,
  signal_key text not null check (signal_key ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now()
);

create index if not exists execution_replays_strategy_idx
  on public.execution_replays(strategy_id, created_at desc);

alter table public.execution_replays enable row level security;
revoke all on public.execution_replays from anon;
revoke all on public.execution_replays from authenticated;

create or replace function public.mt5_strategy_snapshot_hash(p_strategy_id uuid)
returns text
language sql stable security invoker
set search_path = public
as $$
  select encode(
    extensions.digest(
      convert_to(concat_ws(
        chr(31),
        coalesce(strategy_id::text, ''),
        coalesce(raw_strategy_text, ''),
        coalesce(live_symbol, ''),
        coalesce(live_timeframe, ''),
        coalesce(updated_at::text, ''),
        coalesce(live_approved::text, '')
      ), 'utf8'),
      'sha256'
    ),
    'hex'
  )
  from public.strategies
  where strategy_id = p_strategy_id
$$;

create or replace function public.mt5_execution_manifest(p_token_hash text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user uuid;
  v_rows jsonb;
begin
  select user_id into v_user
  from public.broker_accounts
  where connector_type='mt5'
    and bridge_enabled=true
    and bridge_token_hash=p_token_hash
    and bridge_token_revoked_at is null
    and (bridge_token_expires_at is null or bridge_token_expires_at > now())
  limit 1;

  if v_user is null then
    raise exception 'Invalid or expired MT5 bridge token';
  end if;

  select coalesce(jsonb_agg(jsonb_build_object(
    'strategy_id', s.strategy_id,
    'name', s.name,
    'symbol', coalesce(s.live_symbol, ''),
    'timeframe', coalesce(s.live_timeframe, '15m'),
    'live_approved', coalesce(s.live_approved, false),
    'updated_at', s.updated_at,
    'snapshot_hash', public.mt5_strategy_snapshot_hash(s.strategy_id),
  ) order by s.created_at desc), '[]'::jsonb)
  into v_rows
  from public.strategies s
  where s.user_id=v_user
    and coalesce(s.live_approved,false)=true
;
  return v_rows;
end
$$;

revoke all on function public.mt5_execution_manifest(text) from public;
grant execute on function public.mt5_execution_manifest(text) to anon, authenticated;

create or replace function public.mt5_issue_execution_certificate(
  p_token_hash text,
  p_strategy_id uuid,
  p_snapshot_hash text,
  p_certificate_hash text,
  p_expires_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user uuid;
  v_current_hash text;
  v_approved boolean;
begin
  select user_id into v_user
  from public.broker_accounts
  where connector_type='mt5'
    and bridge_enabled=true
    and bridge_token_hash=p_token_hash
    and bridge_token_revoked_at is null
    and (bridge_token_expires_at is null or bridge_token_expires_at > now())
  limit 1;

  if v_user is null then raise exception 'Invalid or expired MT5 bridge token'; end if;
  if p_expires_at <= now() or p_expires_at > now() + interval '10 minutes' then
    raise exception 'Invalid certificate expiry';
  end if;

  select public.mt5_strategy_snapshot_hash(strategy_id), coalesce(live_approved,false)
  into v_current_hash, v_approved, v_paused
  from public.strategies
  where strategy_id=p_strategy_id and user_id=v_user;

  if v_current_hash is null then raise exception 'Strategy not found'; end if;
  if not v_approved then raise exception 'Strategy is not live approved'; end if;
  if v_current_hash <> p_snapshot_hash then raise exception 'Strategy snapshot changed'; end if;
  if p_certificate_hash !~ '^[0-9a-f]{64}$' then raise exception 'Invalid certificate hash'; end if;

  insert into public.execution_certificates(
    strategy_id,user_id,snapshot_hash,certificate_hash,issued_at,expires_at,revoked_at,last_heartbeat_at
  ) values (
    p_strategy_id,v_user,p_snapshot_hash,p_certificate_hash,now(),p_expires_at,null,now()
  )
  on conflict(strategy_id) do update set
    user_id=excluded.user_id,
    snapshot_hash=excluded.snapshot_hash,
    certificate_hash=excluded.certificate_hash,
    issued_at=excluded.issued_at,
    expires_at=excluded.expires_at,
    revoked_at=null,
    last_heartbeat_at=now();

  return jsonb_build_object(
    'strategy_id',p_strategy_id,
    'snapshot_hash',p_snapshot_hash,
    'expires_at',p_expires_at
  );
end
$$;

revoke all on function public.mt5_issue_execution_certificate(text,uuid,text,text,timestamptz) from public;
grant execute on function public.mt5_issue_execution_certificate(text,uuid,text,text,timestamptz) to anon, authenticated;

create or replace function public.mt5_authorize_live_signal(
  p_token_hash text,
  p_strategy_id uuid,
  p_snapshot_hash text,
  p_certificate_hash text,
  p_nonce uuid,
  p_signal_key text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user uuid;
  v_cert public.execution_certificates%rowtype;
  v_current_hash text;
  v_approved boolean;
  v_paused boolean;
begin
  select user_id into v_user
  from public.broker_accounts
  where connector_type='mt5'
    and bridge_enabled=true
    and bridge_token_hash=p_token_hash
    and bridge_token_revoked_at is null
    and (bridge_token_expires_at is null or bridge_token_expires_at > now())
  limit 1;

  if v_user is null then raise exception 'Invalid or expired MT5 bridge token'; end if;

  if p_signal_key !~ '^[0-9a-f]{64}$' then raise exception 'Invalid signal key'; end if;

  select * into v_cert
  from public.execution_certificates
  where strategy_id=p_strategy_id and user_id=v_user
  for update;

  if v_cert.id is null then raise exception 'Execution certificate required'; end if;
  if v_cert.revoked_at is not null or v_cert.expires_at <= now() then raise exception 'Execution certificate expired or revoked'; end if;
  if v_cert.certificate_hash <> p_certificate_hash then raise exception 'Execution certificate mismatch'; end if;
  if v_cert.snapshot_hash <> p_snapshot_hash then raise exception 'Execution certificate snapshot mismatch'; end if;

  select public.mt5_strategy_snapshot_hash(strategy_id), coalesce(live_approved,false)
  into v_current_hash, v_approved, v_paused
  from public.strategies
  where strategy_id=p_strategy_id and user_id=v_user;

  if v_current_hash is null then raise exception 'Strategy not found'; end if;
  if not v_approved then raise exception 'Strategy is not live approved'; end if;
  if v_current_hash <> p_snapshot_hash then raise exception 'Strategy changed after certificate issuance'; end if;

  insert into public.execution_replays(nonce,strategy_id,user_id,signal_key)
  values(p_nonce,p_strategy_id,v_user,p_signal_key);

  update public.execution_certificates
  set last_heartbeat_at=now()
  where id=v_cert.id;

  return jsonb_build_object('authorized',true,'strategy_id',p_strategy_id,'nonce',p_nonce);
exception
  when unique_violation then
    raise exception 'Replay detected: execution nonce already consumed';
end
$$;

revoke all on function public.mt5_authorize_live_signal(text,uuid,text,text,uuid,text) from public;
grant execute on function public.mt5_authorize_live_signal(text,uuid,text,text,uuid,text) to anon, authenticated;

create or replace function public.mt5_revoke_execution_certificate(p_strategy_id uuid)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare v_user uuid;
begin
  v_user := auth.uid();
  if v_user is null then raise exception 'Authentication required'; end if;
  update public.execution_certificates
  set revoked_at=now()
  where strategy_id=p_strategy_id and user_id=v_user;
  return found;
end
$$;

revoke all on function public.mt5_revoke_execution_certificate(uuid) from public;
grant execute on function public.mt5_revoke_execution_certificate(uuid) to authenticated;
