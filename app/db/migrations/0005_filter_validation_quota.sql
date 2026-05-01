-- 0005_filter_validation_quota.sql — per-user monthly quota for filter
-- quality checks.
--
-- Filter validation calls the LLM with a tiny prompt (one filter text, no
-- job description) so each call is a fraction of an evaluation's cost. We
-- still cap them per month, separately from evaluations_used, so a user
-- typing dozens of filters can't drain their job-evaluation quota — and so
-- a malicious user mass-spamming /filters/validate is bounded.
--
-- Defaults match the in-code fallback in app/services/quota.py.

alter table public.profiles
    add column if not exists monthly_filter_validation_limit int not null default 30;

alter table public.usage_counters
    add column if not exists filter_validations_used int not null default 0;

-- Atomic increment, mirroring increment_usage from 0002. Returns the new
-- counter so the caller can decide whether to 402 in the same round trip.
create or replace function public.increment_filter_validation_usage(
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
    insert into public.usage_counters (user_id, year_month, filter_validations_used)
    values (p_user_id, p_year_month, 1)
    on conflict (user_id, year_month)
    do update set filter_validations_used = public.usage_counters.filter_validations_used + 1
    returning filter_validations_used into new_count;
    return new_count;
end;
$$;

revoke all on function public.increment_filter_validation_usage(uuid, text) from public;
revoke all on function public.increment_filter_validation_usage(uuid, text) from anon;
revoke all on function public.increment_filter_validation_usage(uuid, text) from authenticated;
