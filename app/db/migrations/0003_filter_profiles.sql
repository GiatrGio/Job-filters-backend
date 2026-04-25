-- 0003_filter_profiles.sql — multi-profile filter sets.
--
-- Users can group filters into named profiles ("Software Engineer",
-- "Data Engineer", …) and switch between them. Exactly one profile per
-- user is active at a time; /evaluate uses the active profile's filters.
--
-- Naming: this table is NOT public.profiles (that's the existing user-
-- account metadata table — plan, monthly limit). The user-facing term in
-- the UI is "profile"; in the schema/code we use filter_profile to keep
-- the two distinct.

-- ---------------------------------------------------------------------------
-- filter_profiles
-- ---------------------------------------------------------------------------
create table if not exists public.filter_profiles (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users on delete cascade,
    name text not null check (char_length(name) between 1 and 50),
    position int not null default 0,
    is_active boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Exactly one active profile per user. Partial unique index over the
-- subset of rows where is_active is true.
create unique index if not exists filter_profiles_one_active_per_user
    on public.filter_profiles (user_id) where is_active;

create index if not exists filter_profiles_user_position_idx
    on public.filter_profiles (user_id, position);

alter table public.filter_profiles enable row level security;

drop policy if exists "filter_profiles_self_all" on public.filter_profiles;
create policy "filter_profiles_self_all" on public.filter_profiles
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop trigger if exists filter_profiles_set_updated_at on public.filter_profiles;
create trigger filter_profiles_set_updated_at
    before update on public.filter_profiles
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Backfill: every existing user gets a "Default" profile, set active.
-- ---------------------------------------------------------------------------
insert into public.filter_profiles (user_id, name, position, is_active)
select p.id, 'Default', 0, true
from public.profiles p
where not exists (
    select 1 from public.filter_profiles fp where fp.user_id = p.id
);

-- ---------------------------------------------------------------------------
-- filters: add profile_id, backfill from the user's (only) Default profile,
-- then enforce NOT NULL. Also tighten the text length to 200 chars.
-- ---------------------------------------------------------------------------
alter table public.filters
    add column if not exists profile_id uuid references public.filter_profiles on delete cascade;

update public.filters f
set profile_id = (
    select fp.id from public.filter_profiles fp
    where fp.user_id = f.user_id and fp.is_active
    limit 1
)
where f.profile_id is null;

alter table public.filters alter column profile_id set not null;

drop index if exists filters_user_position_idx;
create index if not exists filters_profile_position_idx
    on public.filters (profile_id, position);

-- Replace the (anonymous) char_length(text) check with a named one capping at 200.
do $$
declare
    cname text;
begin
    select con.conname into cname
    from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    where rel.relname = 'filters'
      and rel.relnamespace = 'public'::regnamespace
      and con.contype = 'c'
      and pg_get_constraintdef(con.oid) ilike '%char_length(text)%';
    if cname is not null then
        execute format('alter table public.filters drop constraint %I', cname);
    end if;
end $$;

alter table public.filters
    add constraint filters_text_length check (char_length(text) between 1 and 200);

-- ---------------------------------------------------------------------------
-- New-user trigger: also create a Default filter profile.
-- ---------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id) values (new.id) on conflict (id) do nothing;
    insert into public.filter_profiles (user_id, name, position, is_active)
        values (new.id, 'Default', 0, true)
        on conflict do nothing;
    return new;
end;
$$;
