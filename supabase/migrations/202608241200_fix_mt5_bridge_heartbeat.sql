-- Keep last_verified_at as a real bridge heartbeat.
-- mt5_claim_jobs is called by the Windows bridge every poll interval.
create or replace function public.mt5_claim_jobs(p_token_hash text)
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  v_user uuid;
  v_jobs jsonb;
begin
  select user_id into v_user
  from public.broker_accounts
  where connector_type='mt5'
    and bridge_enabled=true
    and bridge_token_hash=p_token_hash
  limit 1;

  if v_user is null then
    raise exception 'Invalid MT5 bridge token';
  end if;

  update public.broker_accounts
  set last_verified_at=now()
  where user_id=v_user
    and connector_type='mt5'
    and bridge_enabled=true
    and bridge_token_hash=p_token_hash;

  with claimed as (
    update public.mt5_bridge_jobs j
    set status='processing', updated_at=now()
    where j.id in (
      select id
      from public.mt5_bridge_jobs
      where user_id=v_user
        and status='queued'
        and expires_at>now()
      order by created_at asc
      limit 5
    )
    returning j.*
  )
  select coalesce(jsonb_agg(to_jsonb(claimed) order by created_at asc),'[]'::jsonb)
  into v_jobs
  from claimed;

  return v_jobs;
end
$function$;

-- Also refresh the heartbeat when a bridge completes or rejects a job.
create or replace function public.mt5_complete_job(
  p_token_hash text,
  p_job_id uuid,
  p_status text,
  p_rates jsonb default null,
  p_account jsonb default null,
  p_error text default null,
  p_result jsonb default null
)
returns boolean
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  v_user uuid;
  v_count int;
begin
  select user_id into v_user
  from public.broker_accounts
  where connector_type='mt5'
    and bridge_enabled=true
    and bridge_token_hash=p_token_hash
  limit 1;

  if v_user is null then
    raise exception 'Invalid MT5 bridge token';
  end if;

  update public.broker_accounts
  set last_verified_at=now()
  where user_id=v_user
    and connector_type='mt5'
    and bridge_enabled=true
    and bridge_token_hash=p_token_hash;

  update public.mt5_bridge_jobs
  set status=p_status,
      rates=coalesce(p_rates,rates),
      account=coalesce(p_account,account),
      error=coalesce(p_error,error),
      result=coalesce(p_result,result),
      updated_at=now()
  where id=p_job_id and user_id=v_user;

  get diagnostics v_count=row_count;
  if v_count=0 then
    raise exception 'Bridge job not found';
  end if;

  return true;
end
$function$;
