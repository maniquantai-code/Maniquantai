-- A bridge token is an authorization credential, not proof that an MT5
-- terminal is already connected. The initial registration therefore creates
-- a minimal broker_accounts row when the user has never linked MT5 before.
create or replace function public.mt5_register_bridge(
  p_token_hash text,
  p_expires_at timestamptz default now() + interval '30 days'
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
  v_user uuid;
begin
  v_user := auth.uid();
  if v_user is null then raise exception 'Authentication required'; end if;

  select id into v_id
  from public.broker_accounts
  where user_id = v_user and connector_type = 'mt5'
  order by created_at desc
  limit 1;

  if v_id is null then
    insert into public.broker_accounts (
      user_id, connector_type, connector_name, label,
      bridge_token_hash, bridge_token_expires_at,
      bridge_token_revoked_at, bridge_enabled, last_verified_at
    ) values (
      v_user, 'mt5', 'MetaTrader 5', 'ManiQuantAI MT5 Bridge',
      p_token_hash, p_expires_at, null, true, null
    )
    returning id into v_id;
  else
    update public.broker_accounts
    set bridge_token_hash = p_token_hash,
        bridge_token_expires_at = p_expires_at,
        bridge_token_revoked_at = null,
        bridge_enabled = true,
        last_verified_at = null
    where id = v_id;
  end if;

  return jsonb_build_object('broker_account_id', v_id, 'bridge_enabled', true, 'expires_at', p_expires_at);
end
$$;

grant execute on function public.mt5_register_bridge(text,timestamptz) to authenticated;
