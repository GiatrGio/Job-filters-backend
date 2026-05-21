-- Beta free tier limits.
--
-- Lower the default free monthly evaluation allowance from 200 to 50.
-- Existing free profiles that are still on the old default are moved down;
-- manual overrides with other values are left alone.

alter table public.profiles
    alter column monthly_eval_limit set default 50;

update public.profiles
    set monthly_eval_limit = 50
    where plan = 'free' and monthly_eval_limit = 200;
