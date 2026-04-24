-- 0002_atomic_quota.sql — atomic increment for usage_counters.
--
-- Replaces the backend's read-then-write pattern, which under concurrent
-- cache misses for the same user in the same second could undercount by one.
-- This function uses INSERT ... ON CONFLICT DO UPDATE RETURNING so the bump
-- happens in a single transaction inside Postgres.

create or replace function public.increment_usage(
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
    insert into public.usage_counters (user_id, year_month, evaluations_used)
    values (p_user_id, p_year_month, 1)
    on conflict (user_id, year_month)
    do update set evaluations_used = public.usage_counters.evaluations_used + 1
    returning evaluations_used into new_count;
    return new_count;
end;
$$;

-- Lock this function down: callers should never be able to increment a
-- different user's counter. The backend invokes it with the secret key
-- (bypasses checks), and we revoke execution from the anon / authenticated
-- roles to prevent the extension from calling it directly.
revoke all on function public.increment_usage(uuid, text) from public;
revoke all on function public.increment_usage(uuid, text) from anon;
revoke all on function public.increment_usage(uuid, text) from authenticated;
