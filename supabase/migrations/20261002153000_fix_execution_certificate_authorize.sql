-- Fix the authorization RPC target list for deployed databases.
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
  into v_current_hash, v_approved
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
