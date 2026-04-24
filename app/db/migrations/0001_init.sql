-- 0001_init.sql — initial schema for the LinkedIn Job Filter backend.
-- Apply via Supabase CLI (`supabase db push`) or paste into the SQL editor.
--
-- RLS is enabled on every user-scoped table. Policies allow users to read and
-- mutate only their own rows via the anon/publishable key. The backend uses
-- the secret key (bypasses RLS) for cache + quota writes.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- profiles: per-user metadata, auto-created on signup by trigger below.
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
    id uuid primary key references auth.users on delete cascade,
    plan text not null default 'free',
    monthly_eval_limit int not null default 50,
    created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

drop policy if exists "profiles_self_read" on public.profiles;
create policy "profiles_self_read" on public.profiles
    for select using (auth.uid() = id);

drop policy if exists "profiles_self_update" on public.profiles;
create policy "profiles_self_update" on public.profiles
    for update using (auth.uid() = id) with check (auth.uid() = id);

-- Auto-create a profile row whenever a new auth.users row appears.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id) values (new.id)
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- filters: free-text filter criteria, one row per filter per user.
-- ---------------------------------------------------------------------------
create table if not exists public.filters (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users on delete cascade,
    text text not null check (char_length(text) between 1 and 500),
    position int not null default 0,
    enabled boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists filters_user_position_idx
    on public.filters (user_id, position);

alter table public.filters enable row level security;

drop policy if exists "filters_self_all" on public.filters;
create policy "filters_self_all" on public.filters
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists filters_set_updated_at on public.filters;
create trigger filters_set_updated_at
    before update on public.filters
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- evaluations: permanent cache of LLM evaluations, keyed by filters_hash so
-- a filter edit naturally invalidates stale entries.
-- ---------------------------------------------------------------------------
create table if not exists public.evaluations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users on delete cascade,
    linkedin_job_id text not null,
    job_title text,
    job_company text,
    job_url text,
    filters_hash text not null,
    results jsonb not null,
    provider text not null,
    model text not null,
    tokens_input int,
    tokens_output int,
    created_at timestamptz not null default now(),
    unique (user_id, linkedin_job_id, filters_hash)
);

create index if not exists evaluations_user_job_idx
    on public.evaluations (user_id, linkedin_job_id);

alter table public.evaluations enable row level security;

drop policy if exists "evaluations_self_read" on public.evaluations;
create policy "evaluations_self_read" on public.evaluations
    for select using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- usage_counters: per-user monthly LLM-call count. Incremented only on miss.
-- ---------------------------------------------------------------------------
create table if not exists public.usage_counters (
    user_id uuid not null references auth.users on delete cascade,
    year_month text not null,
    evaluations_used int not null default 0,
    primary key (user_id, year_month)
);

alter table public.usage_counters enable row level security;

drop policy if exists "usage_counters_self_read" on public.usage_counters;
create policy "usage_counters_self_read" on public.usage_counters
    for select using (auth.uid() = user_id);
