-- AI-LOGISTICS COPILOT — PostgreSQL (Railway Postgres, локально, або будь-який керований Postgres)
-- Запуск: підключись до бази й виконай у SQL-клієнті (Railway має вкладку Query / або psql).

create extension if not exists "pgcrypto";

create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    telegram_id bigint not null unique,
    history jsonb not null default '[]'::jsonb,
    pending_draft text,
    pending_reply_to_message_id bigint,
    last_updated timestamptz not null default now()
);

create index if not exists idx_conversations_telegram_id
    on public.conversations (telegram_id);

create table if not exists public.claims (
    id uuid primary key default gen_random_uuid(),
    ttn text not null,
    user_id bigint,
    status text not null default 'open',
    description text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_claims_ttn on public.claims (ttn);
create index if not exists idx_claims_user_id on public.claims (user_id);
