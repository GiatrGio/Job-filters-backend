-- 0007_application_deadline.sql — add an application deadline date.
--
-- Mirrors `applied_at` in shape (timestamptz, nullable). Indexed on
-- (user_id, deadline_at) so the upcoming Calendar view can cheaply
-- pull "all my deadlines this month" without a full table scan.
--
-- Apply order: AFTER 0001..0006. Idempotent.

alter table public.applications
    add column if not exists deadline_at timestamptz;

create index if not exists applications_user_deadline_idx
    on public.applications (user_id, deadline_at)
    where deadline_at is not null;
