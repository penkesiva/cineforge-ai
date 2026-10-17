-- YouTube discovery runs, 15-minute cache, and daily API-quota counters.
-- Rows are deleted after youtube retention (default 24h). No statistical history.

begin;

create table public.discovery_runs (
    id               text primary key,
    tenant_id        text not null references public.tenants (id),
    idempotency_key  text not null,
    payload          jsonb not null,
    retrieved_at     timestamptz not null,
    unique (tenant_id, idempotency_key)
);
create index discovery_runs_retrieved_idx on public.discovery_runs (retrieved_at);

create table public.discovery_cache (
    tenant_id   text not null,
    cache_key   text not null,
    payload     jsonb not null,
    expires_at  timestamptz not null,
    primary key (tenant_id, cache_key)
);
create index discovery_cache_expires_idx on public.discovery_cache (expires_at);

create table public.discovery_quota (
    credential_hash text not null,
    method          text not null check (method in ('search', 'videos')),
    day             date not null,
    used            integer not null check (used >= 0),
    allowance       integer not null check (allowance >= 0),
    primary key (credential_hash, method, day)
);

alter table public.discovery_runs enable row level security;
alter table public.discovery_cache enable row level security;
alter table public.discovery_quota enable row level security;

commit;
