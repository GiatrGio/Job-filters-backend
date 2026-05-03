-- 0009_application_interviews.sql — interview rounds attached to a job.
--
-- Free-form `title` (e.g. "Phone screen", "Tech round 2", "Bar raiser") rather
-- than a fixed enum: real interview processes vary too much to pre-categorise.
-- We can add an optional category column later if analytics needs it.
--
-- `user_id` is denormalised on purpose. The upcoming Calendar view will query
-- `application_interviews where user_id = X and scheduled_at between …` across
-- ALL the user's applications — joining through `applications` for every event
-- would be wasteful. The (user_id, scheduled_at) index supports that path.
--
-- `outcome` is null while pending; non-null once the user marks the round.
-- It does NOT auto-update the parent application's status (we surface that as
-- a UI suggestion instead, not a silent side effect).
--
-- Apply order: AFTER 0001..0008. Idempotent.

create table if not exists public.application_interviews (
    id uuid primary key default gen_random_uuid(),
    application_id uuid not null references public.applications on delete cascade,
    user_id uuid not null references auth.users on delete cascade,
    title text not null check (char_length(title) between 1 and 200),
    scheduled_at timestamptz not null,
    duration_minutes int not null default 60 check (duration_minutes between 1 and 1440),
    location text check (char_length(location) <= 500),
    interviewer text check (char_length(interviewer) <= 500),
    notes text check (char_length(notes) <= 2000),
    outcome text check (outcome in ('passed','failed','no_show','cancelled')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists application_interviews_application_idx
    on public.application_interviews (application_id, scheduled_at);

-- Calendar-view path: "all my interviews in this date range".
create index if not exists application_interviews_user_scheduled_idx
    on public.application_interviews (user_id, scheduled_at);

alter table public.application_interviews enable row level security;

drop policy if exists "application_interviews_self_all" on public.application_interviews;
create policy "application_interviews_self_all" on public.application_interviews
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop trigger if exists application_interviews_set_updated_at on public.application_interviews;
create trigger application_interviews_set_updated_at
    before update on public.application_interviews
    for each row execute function public.set_updated_at();
