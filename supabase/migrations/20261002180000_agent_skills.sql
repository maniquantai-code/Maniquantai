create table if not exists public.agent_skills (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null,
 agent_name text not null check (agent_name in ('research','strategy_compiler','backtest','risk','paper_trading','execution','market_intelligence','portfolio','compliance')),
 name text not null,
 version text not null default '1.0.0',
 content text not null,
 sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
 source text not null default 'user' check (source in ('user','default')),
 active boolean not null default true,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create index if not exists agent_skills_user_agent_idx on public.agent_skills(user_id,agent_name,active);
alter table public.agent_skills enable row level security;
drop policy if exists agent_skills_owner_select on public.agent_skills;
create policy agent_skills_owner_select on public.agent_skills for select to authenticated using ((select auth.uid())=user_id);
drop policy if exists agent_skills_owner_insert on public.agent_skills;
create policy agent_skills_owner_insert on public.agent_skills for insert to authenticated with check ((select auth.uid())=user_id);
drop policy if exists agent_skills_owner_update on public.agent_skills;
create policy agent_skills_owner_update on public.agent_skills for update to authenticated using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
drop policy if exists agent_skills_owner_delete on public.agent_skills;
create policy agent_skills_owner_delete on public.agent_skills for delete to authenticated using ((select auth.uid())=user_id);
revoke all on public.agent_skills from anon,authenticated;
