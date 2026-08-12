-- Free tier allowances, post-beta.
--
--   evaluations   50 -> 200   (0012 had cut this from 200 to 50 for the beta)
--   cover letters  1 ->   5   (0015 shipped with 1)
--
-- Both limits are enforced from the PROFILE COLUMN, not from config: the env
-- vars in app/config.py are only the NULL fallback and what billing/admin write
-- on a plan change. So bumping config alone would leave every existing user on
-- their stored 50/1 — this migration is what actually raises them.
--
-- Tracked jobs need no migration: that limit has no column and no meter, it's a
-- live count against `free_tracked_jobs_limit` (5 -> 20 in the same change).
--
-- Backfill only lifts rows that are still on the exact old default, mirroring
-- 0012 and 0015. A free profile deliberately set to some other value (admin
-- tooling, a manual throttle) is an override and is left alone.

alter table public.profiles
    alter column monthly_eval_limit set default 200;

update public.profiles
    set monthly_eval_limit = 200
    where plan = 'free' and monthly_eval_limit = 50;

alter table public.profiles
    alter column monthly_cover_letter_limit set default 5;

update public.profiles
    set monthly_cover_letter_limit = 5
    where plan = 'free' and monthly_cover_letter_limit = 1;
