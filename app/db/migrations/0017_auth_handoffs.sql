-- One-time extension -> website authentication grants.
--
-- Only a SHA-256 hash of the browser-visible ticket is stored. Grants expire
-- after a short application-configured TTL and are deleted atomically when
-- consumed. RLS has no client policies: only the backend secret key can touch
-- this table or its consume function.

create table if not exists public.auth_handoffs (
    id uuid primary key default gen_random_uuid(),
    token_hash text not null unique,
    user_id uuid not null references auth.users on delete cascade,
    destination text not null,
    expires_at timestamptz not null,
    created_at timestamptz not null default now(),
    constraint auth_handoffs_destination_internal
        check (
            left(destination, 1) = '/'
            and left(destination, 2) <> '//'
            and position(chr(92) in destination) = 0
        )
);

create index if not exists auth_handoffs_expires_at_idx
    on public.auth_handoffs (expires_at);

alter table public.auth_handoffs enable row level security;

create or replace function public.consume_auth_handoff(p_token_hash text)
returns table(user_id uuid, destination text)
language plpgsql
security definer
set search_path = public
as $$
begin
    -- Every exchange also clears abandoned tickets. Creation performs the
    -- same cleanup so expired rows stay bounded even when users close tabs.
    delete from public.auth_handoffs where expires_at < now();

    return query
    delete from public.auth_handoffs as handoff
    where handoff.token_hash = p_token_hash
      and handoff.expires_at >= now()
    returning handoff.user_id, handoff.destination;
end;
$$;

revoke all on function public.consume_auth_handoff(text) from public;
revoke all on function public.consume_auth_handoff(text) from anon;
revoke all on function public.consume_auth_handoff(text) from authenticated;
