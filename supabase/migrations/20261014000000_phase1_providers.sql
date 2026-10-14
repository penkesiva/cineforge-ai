-- CineForge AI Phase 1: provider settings (Sources page), ledger status reason.
-- API keys are NOT stored here: they live encrypted in Supabase Vault
-- (vault.secrets, name 'cineforge:<tenant>:<provider>'), read only by the app role.

begin;

create extension if not exists supabase_vault;

-- Per-tenant routing preference per provider. Lower priority wins.
create table public.provider_settings (
    tenant_id   text not null references public.tenants (id),
    provider    text not null,
    enabled     boolean not null,
    priority    integer not null default 100 check (priority between 0 and 1000),
    updated_at  timestamptz not null default now(),
    primary key (tenant_id, provider)
);

alter table public.provider_settings enable row level security;

-- Why a ledger row was released/failed, or an overspend note on commit.
alter table public.cost_ledger add column status_reason text;

commit;
