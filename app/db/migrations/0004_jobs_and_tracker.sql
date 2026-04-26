-- 0004_jobs_and_tracker.sql — generalize jobs to be source-agnostic and add
-- the application tracker.
--
-- Three logical changes:
--   1. evaluations: rename linkedin_job_id → job_id, add `source` text column,
--      and replace the unique constraint + supporting index.
--   2. profiles: bump default monthly_eval_limit to 200, add a CV tailoring
--      counter limit, and lift existing free users to the new floor.
--   3. New table public.applications — the website's tracker. One row per
--      (user_id, source, external_id), so the extension's "Track this job"
--      call is naturally idempotent. RLS self-only.
--   4. usage_counters: add cv_tailorings_used so the same row tracks both
--      meters per (user, month).
--
-- Apply order: AFTER 0001..0003. This file is idempotent where Postgres lets
-- it be (`if not exists`, `do $$` blocks for renames). Re-running on a fresh
-- DB after 0001..0003 is safe.

-- ---------------------------------------------------------------------------
-- 1. evaluations: source + job_id rename
-- ---------------------------------------------------------------------------

-- Rename column linkedin_job_id → job_id (only if old name still exists).
do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'evaluations'
          and column_name = 'linkedin_job_id'
    ) then
        alter table public.evaluations rename column linkedin_job_id to job_id;
    end if;
end $$;

-- Add the source column. Backfill existing rows to 'linkedin' (everything
-- before this migration was LinkedIn-only), then enforce NOT NULL with no
-- default so future writers must specify the source explicitly.
alter table public.evaluations
    add column if not exists source text;

update public.evaluations
    set source = 'linkedin'
    where source is null;

alter table public.evaluations
    alter column source set not null;

-- Drop the old (user_id, linkedin_job_id, filters_hash) unique constraint
-- regardless of its generated name, plus any supporting index that referenced
-- the old column name.
do $$
declare
    cname text;
begin
    select con.conname into cname
    from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    where rel.relname = 'evaluations'
      and rel.relnamespace = 'public'::regnamespace
      and con.contype = 'u'
      and pg_get_constraintdef(con.oid) ilike '%filters_hash%'
      and pg_get_constraintdef(con.oid) not ilike '%source%';
    if cname is not null then
        execute format('alter table public.evaluations drop constraint %I', cname);
    end if;
end $$;

drop index if exists evaluations_user_job_idx;

-- New unique constraint includes source, so the same external job_id from
-- different sources never collides. The backend's cache lookup is keyed on
-- (user_id, source, job_id, filters_hash).
alter table public.evaluations
    add constraint evaluations_user_source_job_hash_key
    unique (user_id, source, job_id, filters_hash);

create index if not exists evaluations_user_source_job_idx
    on public.evaluations (user_id, source, job_id);

-- ---------------------------------------------------------------------------
-- 2. profiles: tier limits
-- ---------------------------------------------------------------------------

alter table public.profiles
    alter column monthly_eval_limit set default 200;

alter table public.profiles
    add column if not exists monthly_cv_tailoring_limit int not null default 0;

-- Lift existing free users still at the old default of 50 to the new 200.
-- Don't touch users who were manually bumped above 200.
update public.profiles
    set monthly_eval_limit = 200
    where plan = 'free' and monthly_eval_limit < 200;

-- ---------------------------------------------------------------------------
-- 3. applications (tracker)
-- ---------------------------------------------------------------------------

create table if not exists public.applications (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users on delete cascade,
    source text not null,
    external_id text not null,
    title text,
    company text,
    location text,
    url text,
    description text,
    status text not null default 'saved'
        check (status in ('saved','applied','interviewing','offer','rejected','withdrawn')),
    applied_at timestamptz,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, source, external_id)
);

create index if not exists applications_user_status_idx
    on public.applications (user_id, status);

create index if not exists applications_user_updated_idx
    on public.applications (user_id, updated_at desc);

alter table public.applications enable row level security;

drop policy if exists "applications_self_all" on public.applications;
create policy "applications_self_all" on public.applications
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Reuse the set_updated_at() function defined in 0001.
drop trigger if exists applications_set_updated_at on public.applications;
create trigger applications_set_updated_at
    before update on public.applications
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- 4. usage_counters: CV tailorings counter
-- ---------------------------------------------------------------------------

alter table public.usage_counters
    add column if not exists cv_tailorings_used int not null default 0;
