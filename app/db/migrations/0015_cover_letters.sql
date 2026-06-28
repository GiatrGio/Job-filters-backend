-- 0015_cover_letters.sql — on-demand customized cover-letter generation.
--
-- Adds a third monthly meter (alongside evaluations_used / filter_validations_used),
-- a per-user settings row holding the candidate's identity block + default
-- generation instructions, and widens the llm_calls call_type set.
--
-- PRIVACY (read before touching cover_letter_settings): unlike cv_profiles —
-- which deliberately stores NO identity — this feature explicitly stores the
-- contact details the user enters so we can produce a complete, ready-to-send
-- letter (their decision, disclosed in the privacy policy's "Cover-letter
-- details" section). The GENERATED LETTER TEXT is NOT stored here or anywhere
-- server-side — it is returned to the extension and cached client-side only —
-- and the identity fields are redacted from the llm_calls log (see
-- app/services/llm_calls.build_prompt_payload, call_type='cover_letter'). If you
-- ever start persisting letter text, revisit the privacy policy + retention.

-- Third quota meter. Free = 1 generation/month, Pro = 25 (set on upgrade by
-- billing). Limit lives on the profile so we can bump individuals without a
-- deploy, mirroring monthly_eval_limit / monthly_filter_validation_limit.
alter table public.profiles
    add column if not exists monthly_cover_letter_limit int not null default 1;

-- The column default (1) suits free users. Existing Pro users predate this
-- column, so lift them to the Pro allowance (new upgrades get it from billing;
-- new free signups keep the default 1). Mirrors the 0012 free-limit backfill.
update public.profiles
    set monthly_cover_letter_limit = 25
    where plan = 'pro';

alter table public.usage_counters
    add column if not exists cover_letters_used int not null default 0;

-- Atomic increment, mirroring increment_usage (0002) and
-- increment_filter_validation_usage (0005). Returns the new counter so the
-- caller can 402 in the same round trip.
create or replace function public.increment_cover_letter_usage(
    p_user_id uuid,
    p_year_month text
)
returns int
language plpgsql
security definer
set search_path = public
as $$
declare
    new_count int;
begin
    insert into public.usage_counters (user_id, year_month, cover_letters_used)
    values (p_user_id, p_year_month, 1)
    on conflict (user_id, year_month)
    do update set cover_letters_used = public.usage_counters.cover_letters_used + 1
    returning cover_letters_used into new_count;
    return new_count;
end;
$$;

revoke all on function public.increment_cover_letter_usage(uuid, text) from public;
revoke all on function public.increment_cover_letter_usage(uuid, text) from anon;
revoke all on function public.increment_cover_letter_usage(uuid, text) from authenticated;

-- One settings row per user (primary key = user_id → at most one row). Holds
-- the single global default-instructions block (validated on save like a
-- filter) plus the identity block used to fill the letter's header/signature.
create table if not exists public.cover_letter_settings (
    user_id uuid primary key references auth.users on delete cascade,
    instructions text not null default '',
    full_name text not null default '',
    email text not null default '',
    phone text not null default '',
    location text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- RLS on, no policies: same stance as cv_profiles / evaluations — only the
-- backend's secret key (which bypasses RLS) touches this table; the extension
-- never reads/writes it directly.
alter table public.cover_letter_settings enable row level security;

-- Two new LLM call types for /admin observability:
--   cover_letter            → per-job letter generation (prompt logged with the
--                             user's identity fields REDACTED; letter text not
--                             persisted server-side).
--   cover_letter_validation → quality check on the default instructions block
--                             (reuses the filter-validation monthly meter).
--   cv_contact              → one-off extraction of the candidate's contact
--                             details from the CV to PREFILL cover-letter
--                             identity fields. Prompt logs the CV text REDACTED
--                             and the extracted contact REDACTED; the contact is
--                             never stored in cv_profiles.
alter table public.llm_calls drop constraint if exists llm_calls_call_type_check;
alter table public.llm_calls add constraint llm_calls_call_type_check
    check (call_type in (
        'job_evaluation',
        'filter_validation',
        'dom_diagnostics',
        'cv_parse',
        'job_fit',
        'cover_letter',
        'cover_letter_validation',
        'cv_contact'
    ));
