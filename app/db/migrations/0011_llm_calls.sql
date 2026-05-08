-- 0011_llm_calls.sql — first-party LLM call observability for local admin UI.
--
-- Prompts can contain full job descriptions. Keep this table backend/admin
-- only, and purge it regularly once it is no longer useful for debugging.

create table if not exists public.llm_calls (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users on delete cascade,
    call_type text not null
        check (call_type in ('job_evaluation', 'filter_validation')),
    provider text not null,
    model text not null,
    status text not null check (status in ('success', 'error')),
    source text,
    external_id text,
    summary text,
    prompt jsonb not null,
    response jsonb,
    error text,
    tokens_input int not null default 0,
    tokens_output int not null default 0,
    cost_usd_micros bigint,
    duration_ms int,
    created_at timestamptz not null default now()
);

create index if not exists llm_calls_created_at_idx
    on public.llm_calls (created_at desc);

create index if not exists llm_calls_user_id_created_at_idx
    on public.llm_calls (user_id, created_at desc);

alter table public.llm_calls enable row level security;
