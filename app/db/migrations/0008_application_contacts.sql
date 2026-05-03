-- 0008_application_contacts.sql — lightweight contacts attached to a job.
--
-- One job can have many contacts (recruiter, hiring manager, tech interviewer);
-- contacts are NOT reusable across jobs in the MVP — if the same recruiter
-- comes up twice the user re-enters them, which is fine at this scale. If we
-- ever want cross-job dedupe, add a `contact_id` FK to a separate `contacts`
-- table later.
--
-- Apply order: AFTER 0001..0007. Idempotent.

create table if not exists public.application_contacts (
    id uuid primary key default gen_random_uuid(),
    application_id uuid not null references public.applications on delete cascade,
    user_id uuid not null references auth.users on delete cascade,
    name text not null check (char_length(name) between 1 and 200),
    role text check (char_length(role) <= 100),
    email text check (char_length(email) <= 320),
    linkedin_url text check (char_length(linkedin_url) <= 500),
    notes text check (char_length(notes) <= 2000),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists application_contacts_application_idx
    on public.application_contacts (application_id, created_at);

create index if not exists application_contacts_user_idx
    on public.application_contacts (user_id);

alter table public.application_contacts enable row level security;

drop policy if exists "application_contacts_self_all" on public.application_contacts;
create policy "application_contacts_self_all" on public.application_contacts
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop trigger if exists application_contacts_set_updated_at on public.application_contacts;
create trigger application_contacts_set_updated_at
    before update on public.application_contacts
    for each row execute function public.set_updated_at();
