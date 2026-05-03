-- 0010_stripe_billing.sql — Stripe subscriptions for canvasjob Pro.
--
-- Pro is EUR 7.99/month, VAT-inclusive. The Stripe Price must be created in
-- Stripe Dashboard with tax behavior = inclusive; the backend enables
-- Checkout automatic tax when configured.

alter table public.profiles
    add column if not exists stripe_customer_id text,
    add column if not exists stripe_subscription_id text,
    add column if not exists stripe_subscription_status text,
    add column if not exists stripe_price_id text,
    add column if not exists stripe_current_period_end timestamptz,
    add column if not exists stripe_cancel_at_period_end boolean not null default false;

create unique index if not exists profiles_stripe_customer_id_key
    on public.profiles (stripe_customer_id)
    where stripe_customer_id is not null;

create unique index if not exists profiles_stripe_subscription_id_key
    on public.profiles (stripe_subscription_id)
    where stripe_subscription_id is not null;

alter table public.profiles
    drop constraint if exists profiles_plan_check;

alter table public.profiles
    add constraint profiles_plan_check check (plan in ('free', 'pro'));

-- Users must not be able to self-upgrade by editing public.profiles with the
-- Supabase publishable key. Profile billing fields are managed by the backend
-- using the Supabase secret key.
drop policy if exists "profiles_self_update" on public.profiles;

create table if not exists public.subscriptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users on delete cascade,
    stripe_customer_id text not null,
    stripe_subscription_id text not null unique,
    stripe_price_id text,
    status text not null,
    current_period_end timestamptz,
    cancel_at_period_end boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists subscriptions_user_id_idx
    on public.subscriptions (user_id);

create index if not exists subscriptions_stripe_customer_id_idx
    on public.subscriptions (stripe_customer_id);

alter table public.subscriptions enable row level security;

drop policy if exists "subscriptions_self_read" on public.subscriptions;
create policy "subscriptions_self_read" on public.subscriptions
    for select using (auth.uid() = user_id);

drop trigger if exists subscriptions_set_updated_at on public.subscriptions;
create trigger subscriptions_set_updated_at
    before update on public.subscriptions
    for each row execute function public.set_updated_at();
