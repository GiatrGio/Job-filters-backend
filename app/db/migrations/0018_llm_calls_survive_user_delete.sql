-- 0018_llm_calls_survive_user_delete.sql — keep LLM cost history when a user
-- deletes their account.
--
-- Every other user-owned table cascades from auth.users, which is exactly what
-- account deletion wants. llm_calls is the exception: it is cost/observability
-- telemetry, not user content, and cascading it would silently rewrite the
-- historical spend reported by /admin every time somebody leaves.
--
-- user_id is already nullable, so switching to `on delete set null` keeps the
-- cost rows while severing the link to the person. The prompts themselves are
-- purged separately (see the retention note in 0011).

alter table public.llm_calls
    drop constraint if exists llm_calls_user_id_fkey;

alter table public.llm_calls
    add constraint llm_calls_user_id_fkey
    foreign key (user_id) references auth.users (id) on delete set null;
