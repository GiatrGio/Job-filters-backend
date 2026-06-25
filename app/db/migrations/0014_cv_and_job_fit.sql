-- 0014_cv_and_job_fit.sql — CV-based job-fit feature.
--
-- Adds two tables and widens the llm_calls call_type set.
--
-- PRIVACY (read before touching cv_profiles): we deliberately do NOT store the
-- uploaded CV file or its raw text. The file is parsed in memory and discarded;
-- only the structured, non-identifying professional signal needed to judge fit
-- is persisted (skills, years, seniority, role titles, domains, education level,
-- languages, a short professional summary). Names, emails, phone numbers,
-- postal addresses, links and employer names are never extracted or stored —
-- the CV-parse prompt forbids it (see app/llm/prompts.py). Keep it that way; if
-- you ever widen what we keep, update the privacy policy's "CV / job fit"
-- section to match.

-- One parsed CV profile per user (primary key = user_id → at most one row).
create table if not exists public.cv_profiles (
    user_id uuid primary key references auth.users on delete cascade,
    profile jsonb not null,
    -- sha256 over the canonical serialization of `profile`. Used as the fit
    -- cache key: re-uploading a CV that parses differently changes this hash and
    -- invalidates prior fit results, without touching the filter-eval cache.
    cv_hash text not null,
    provider text not null,
    model text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.cv_profiles enable row level security;

-- Per-job fit evaluation cache. Mirrors public.evaluations, but keyed on
-- cv_hash instead of filters_hash so fit and filter caches invalidate
-- independently (a filter edit never re-runs fit; a CV change never re-runs
-- filters). No job_description is stored here — same data-minimisation stance as
-- public.evaluations.
create table if not exists public.job_fit_evaluations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users on delete cascade,
    source text not null,
    job_id text not null,
    cv_hash text not null,
    job_title text,
    job_company text,
    job_url text,
    score int not null check (score between 1 and 5),
    dimensions jsonb not null,           -- {"skills":1-5,"experience":1-5,"domain":1-5}
    strengths jsonb not null,            -- [{"point":..., "evidence":...}]
    gaps jsonb not null,                 -- [{"point":..., "evidence":...}]
    summary text not null,
    provider text not null,
    model text not null,
    tokens_input int,
    tokens_output int,
    created_at timestamptz not null default now(),
    unique (user_id, source, job_id, cv_hash)
);

create index if not exists job_fit_evaluations_lookup_idx
    on public.job_fit_evaluations (user_id, source, job_id, cv_hash);

alter table public.job_fit_evaluations enable row level security;

-- Two new LLM call types for /admin observability:
--   cv_parse → one-off CV → structured profile parse (prompt is logged with the
--              raw CV text REDACTED; we never persist CV text anywhere).
--   job_fit  → per-job fit evaluation (candidate profile vs job description).
alter table public.llm_calls drop constraint if exists llm_calls_call_type_check;
alter table public.llm_calls add constraint llm_calls_call_type_check
    check (call_type in (
        'job_evaluation',
        'filter_validation',
        'dom_diagnostics',
        'cv_parse',
        'job_fit'
    ));
