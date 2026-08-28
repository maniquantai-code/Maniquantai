alter table public.broker_accounts add column if not exists bridge_token_expires_at timestamptz, add column if not exists bridge_token_revoked_at timestamptz;

create or replace function public.mt5_register_bridge(p_token_hash text, p_expires_at timestamptz default now() + interval '30 days') returns jsonb language plpgsql security definer set search_path = public as $$
declare v_id uuid; v_user uuid;
begin
 v_user := auth.uid(); if v_user is null then raise exception 'Authentication required'; end if;
 select id into v_id from public.broker_accounts where user_id=v_user and connector_type='mt5' order by created_at desc limit 1;
 if v_id is null then raise exception 'MT5 account not connected'; end if;
 update public.broker_accounts set bridge_token_hash=p_token_hash, bridge_token_expires_at=p_expires_at, bridge_token_revoked_at=null, bridge_enabled=true, last_verified_at=null where id=v_id;
 return jsonb_build_object('broker_account_id',v_id,'bridge_enabled',true,'expires_at',p_expires_at);
end $$;

create or replace function public.mt5_rotate_bridge(p_token_hash text, p_expires_at timestamptz default now() + interval '30 days') returns jsonb language plpgsql security definer set search_path = public as $$
declare v_id uuid; v_user uuid;
begin
 v_user := auth.uid(); if v_user is null then raise exception 'Authentication required'; end if;
 select id into v_id from public.broker_accounts where user_id=v_user and connector_type='mt5' order by created_at desc limit 1;
 if v_id is null then raise exception 'MT5 account not connected'; end if;
 update public.broker_accounts set bridge_token_hash=p_token_hash, bridge_token_expires_at=p_expires_at, bridge_token_revoked_at=null, bridge_enabled=true, last_verified_at=null where id=v_id;
 return jsonb_build_object('broker_account_id',v_id,'bridge_enabled',true,'expires_at',p_expires_at);
end $$;

create or replace function public.mt5_revoke_bridge() returns jsonb language plpgsql security definer set search_path = public as $$
declare v_user uuid; v_count int;
begin
 v_user := auth.uid(); if v_user is null then raise exception 'Authentication required'; end if;
 update public.broker_accounts set bridge_enabled=false, bridge_token_revoked_at=now(), last_verified_at=null where user_id=v_user and connector_type='mt5';
 get diagnostics v_count=row_count;
 return jsonb_build_object('revoked',v_count > 0);
end $$;

create or replace function public.mt5_bridge_status() returns jsonb language plpgsql security definer set search_path = public as $$
declare v_user uuid; v_row record;
begin
 v_user := auth.uid(); if v_user is null then raise exception 'Authentication required'; end if;
 select id, bridge_enabled, bridge_token_expires_at, bridge_token_revoked_at, last_verified_at into v_row from public.broker_accounts where user_id=v_user and connector_type='mt5' order by created_at desc limit 1;
 if v_row.id is null then return jsonb_build_object('connected',false); end if;
 return jsonb_build_object('connected',true,'bridge_enabled',coalesce(v_row.bridge_enabled,false),'expires_at',v_row.bridge_token_expires_at,'revoked_at',v_row.bridge_token_revoked_at,'last_verified_at',v_row.last_verified_at);
end $$;

revoke all on function public.mt5_rotate_bridge(text,timestamptz) from public;
revoke all on function public.mt5_revoke_bridge() from public;
revoke all on function public.mt5_bridge_status() from public;
grant execute on function public.mt5_rotate_bridge(text,timestamptz) to authenticated;
grant execute on function public.mt5_revoke_bridge() to authenticated;
grant execute on function public.mt5_bridge_status() to authenticated;

create or replace function public.mt5_claim_jobs(p_token_hash text) returns jsonb language plpgsql security definer set search_path = public as $$
declare v_user uuid; v_jobs jsonb;
begin
 select user_id into v_user from public.broker_accounts where connector_type='mt5' and bridge_enabled=true and bridge_token_hash=p_token_hash and bridge_token_revoked_at is null and (bridge_token_expires_at is null or bridge_token_expires_at > now()) limit 1;
 if v_user is null then raise exception 'Invalid or expired MT5 bridge token'; end if;
 update public.broker_accounts set last_verified_at=now() where user_id=v_user and connector_type='mt5' and bridge_enabled=true and bridge_token_hash=p_token_hash;
 with claimed as (update public.mt5_bridge_jobs j set status='processing', updated_at=now() where j.id in (select id from public.mt5_bridge_jobs where user_id=v_user and status='queued' and expires_at>now() order by created_at asc limit 5) returning j.*)
 select coalesce(jsonb_agg(to_jsonb(claimed) order by created_at asc),'[]'::jsonb) into v_jobs from claimed;
 return v_jobs;
end $$;

create or replace function public.mt5_complete_job(p_token_hash text, p_job_id uuid, p_status text, p_rates jsonb default null, p_account jsonb default null, p_error text default null, p_result jsonb default null) returns boolean language plpgsql security definer set search_path = public as $$
declare v_user uuid; v_count int;
begin
 select user_id into v_user from public.broker_accounts where connector_type='mt5' and bridge_enabled=true and bridge_token_hash=p_token_hash and bridge_token_revoked_at is null and (bridge_token_expires_at is null or bridge_token_expires_at > now()) limit 1;
 if v_user is null then raise exception 'Invalid or expired MT5 bridge token'; end if;
 update public.broker_accounts set last_verified_at=now() where user_id=v_user and connector_type='mt5' and bridge_enabled=true and bridge_token_hash=p_token_hash;
 update public.mt5_bridge_jobs set status=p_status, rates=coalesce(p_rates,rates), account=coalesce(p_account,account), error=coalesce(p_error,error), result=coalesce(p_result,result), updated_at=now() where id=p_job_id and user_id=v_user;
 get diagnostics v_count=row_count; if v_count=0 then raise exception 'Bridge job not found'; end if; return true;
end $$;