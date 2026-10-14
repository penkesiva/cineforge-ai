-- CineForge AI Phase 0 schema (FROZEN CONTRACT - see docs/architecture/contracts.md).
-- Metadata, provenance, workflow state and the cost ledger live here.
-- Media binaries live in object storage; rows hold references only.
-- Every tenant-owned table carries tenant_id (PRD 3 ENG-15).
-- RLS is enabled with no policies: Supabase anon/authenticated roles get no access.
-- The application connects with a privileged role and scopes by tenant_id itself.

begin;

-- ---------------------------------------------------------------- tenancy
create table public.tenants (
    id          text primary key,
    name        text not null,
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------- configuration
create table public.theme_profiles (
    id          text not null,
    version     integer not null check (version >= 1),
    name        text not null,
    config      jsonb not null,
    created_at  timestamptz not null default now(),
    primary key (id, version)
);

create table public.price_catalog (
    id               bigserial primary key,
    version          text not null,
    provider         text not null,
    model            text not null,
    capability       text not null,
    unit             text not null,
    unit_price       numeric(18, 6) not null check (unit_price >= 0),
    currency         text not null default 'USD',
    credits_per_unit numeric(18, 6),
    effective_from   date not null,
    effective_to     date,
    simulated        boolean not null default true,
    notes            text not null default '',
    unique (version, provider, model, unit)
);

-- ---------------------------------------------------------------- productions
create table public.productions (
    id               text primary key,
    tenant_id        text not null references public.tenants (id),
    theme_id         text not null,
    theme_version    integer not null,
    mode             text not null check (mode in ('economy', 'balanced', 'premium')),
    state            text not null,
    title            text,
    topic            text not null,
    manifest         jsonb not null,
    currency         text not null default 'USD',
    budget_limit     numeric(18, 6) not null check (budget_limit >= 0),
    idempotency_key  text unique,
    lock_version     integer not null default 1,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);
create index productions_tenant_created_idx on public.productions (tenant_id, created_at desc);
create index productions_state_idx on public.productions (state);

-- Immutable audit trail of state changes and notable events.
create table public.production_events (
    id             bigserial primary key,
    production_id  text not null references public.productions (id) on delete cascade,
    tenant_id      text not null,
    event_type     text not null,
    from_state     text,
    to_state       text,
    message        text not null default '',
    payload        jsonb not null default '{}'::jsonb,
    created_at     timestamptz not null default now()
);
create index production_events_production_idx on public.production_events (production_id, id);

create table public.agent_runs (
    id                       text primary key,
    production_id            text not null references public.productions (id) on delete cascade,
    tenant_id                text not null,
    agent_id                 text not null,
    step                     text not null,
    status                   text not null
        check (status in ('queued', 'running', 'succeeded', 'failed', 'skipped')),
    attempt                  integer not null default 1,
    idempotency_key          text not null unique,
    prompt_template_id       text,
    prompt_template_version  integer,
    input_summary            jsonb not null default '{}'::jsonb,
    output                   jsonb,
    output_model             text,
    error                    text,
    estimated_cost           numeric(18, 6) not null default 0,
    actual_cost              numeric(18, 6) not null default 0,
    started_at               timestamptz not null default now(),
    finished_at              timestamptz
);
create index agent_runs_production_idx on public.agent_runs (production_id, started_at);

create table public.review_findings (
    id                     text primary key,
    production_id          text not null references public.productions (id) on delete cascade,
    tenant_id              text not null,
    gate                   text not null,
    severity               text not null check (severity in ('info', 'minor', 'major', 'critical')),
    message                text not null,
    evidence               jsonb not null default '[]'::jsonb,
    affected_artifact_ids  jsonb not null default '[]'::jsonb,
    recommended_fix        text,
    retry_scope            text not null default 'none',
    created_at             timestamptz not null default now()
);
create index review_findings_production_idx on public.review_findings (production_id);

-- ---------------------------------------------------------------- cost monitoring
-- One row per budget scope. scope_key = 'production' or 'scene:<scene_id>'.
-- Invariant (enforced by BudgetService under SELECT ... FOR UPDATE and by CHECK):
--   reserved_amount + actual_amount <= limit_amount
create table public.budgets (
    id               text primary key,
    tenant_id        text not null,
    production_id    text not null references public.productions (id) on delete cascade,
    scope_key        text not null,
    scene_id         text,
    currency         text not null default 'USD',
    limit_amount     numeric(18, 6) not null check (limit_amount >= 0),
    reserved_amount  numeric(18, 6) not null default 0 check (reserved_amount >= 0),
    actual_amount    numeric(18, 6) not null default 0 check (actual_amount >= 0),
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    unique (production_id, scope_key),
    constraint budgets_within_limit check (reserved_amount + actual_amount <= limit_amount)
);

create table public.cost_ledger (
    event_id             text primary key,
    tenant_id            text not null,
    production_id        text not null references public.productions (id) on delete cascade,
    scene_id             text,
    shot_id              text,
    agent_id             text not null,
    provider             text not null,
    model                text not null,
    capability           text not null,
    provider_request_id  text,
    usage_units          numeric(18, 6) not null default 0,
    usage_unit           text not null,
    unit_price_version   text not null,
    estimated_cost       numeric(18, 6) not null default 0,
    reserved_cost        numeric(18, 6) not null default 0,
    actual_cost          numeric(18, 6) not null default 0,
    currency             text not null default 'USD',
    status               text not null check (status in ('reserved', 'committed', 'released', 'failed')),
    attempt              integer not null default 1,
    retry_reason         text,
    cache_hit            boolean not null default false,
    credits_used         numeric(18, 6),
    idempotency_key      text not null unique,
    "timestamp"          timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);
create index cost_ledger_production_idx on public.cost_ledger (production_id, "timestamp");
create index cost_ledger_provider_idx on public.cost_ledger (provider, model);

create table public.credit_balances (
    tenant_id     text not null,
    provider      text not null,
    balance       numeric(18, 6) not null,
    unit          text not null default 'credit',
    is_estimated  boolean not null default true,
    updated_at    timestamptz not null default now(),
    primary key (tenant_id, provider)
);

-- ---------------------------------------------------------------- media
create table public.assets (
    id               text primary key,
    tenant_id        text not null,
    production_id    text references public.productions (id) on delete set null,
    kind             text not null,
    origin           text not null,
    storage_backend  text not null,
    storage_key      text not null,
    uri              text not null,
    content_type     text not null,
    size_bytes       bigint not null check (size_bytes >= 0),
    sha256           text not null,
    perceptual_hash  text,
    width            integer,
    height           integer,
    duration_sec     double precision,
    source_url       text,
    source_provider  text,
    rights_status    text not null check (rights_status in ('approved', 'pending', 'unknown', 'blocked')),
    rights           jsonb not null,
    generation       jsonb,
    usage_cost       numeric(18, 6) not null default 0,
    metadata         jsonb not null default '{}'::jsonb,
    created_at       timestamptz not null default now()
);
create index assets_tenant_production_idx on public.assets (tenant_id, production_id);
create index assets_sha256_idx on public.assets (tenant_id, sha256);

-- Versioned license snapshots (immutable; a new row per re-check).
create table public.asset_licenses (
    id                      bigserial primary key,
    asset_id                text not null references public.assets (id) on delete cascade,
    tenant_id               text not null,
    license_type            text not null,
    license_url             text,
    author                  text,
    attribution_text        text,
    attribution_required    boolean not null default false,
    commercial_use_allowed  boolean,
    modifications_allowed   boolean,
    restrictions            jsonb not null default '[]'::jsonb,
    source_provider         text,
    source_url              text,
    retrieved_at            timestamptz,
    decision                text not null,
    decision_reasons        jsonb not null default '[]'::jsonb,
    policy_version          text not null,
    created_at              timestamptz not null default now()
);
create index asset_licenses_asset_idx on public.asset_licenses (asset_id);

create table public.asset_usages (
    id             bigserial primary key,
    asset_id       text not null references public.assets (id) on delete cascade,
    tenant_id      text not null,
    production_id  text not null references public.productions (id) on delete cascade,
    scene_id       text,
    shot_id        text,
    transform      jsonb not null default '{}'::jsonb,
    usage_cost     numeric(18, 6) not null default 0,
    created_at     timestamptz not null default now()
);
create index asset_usages_production_idx on public.asset_usages (production_id);

-- ---------------------------------------------------------------- security
alter table public.tenants           enable row level security;
alter table public.theme_profiles    enable row level security;
alter table public.price_catalog     enable row level security;
alter table public.productions       enable row level security;
alter table public.production_events enable row level security;
alter table public.agent_runs        enable row level security;
alter table public.review_findings   enable row level security;
alter table public.budgets           enable row level security;
alter table public.cost_ledger       enable row level security;
alter table public.credit_balances   enable row level security;
alter table public.assets            enable row level security;
alter table public.asset_licenses    enable row level security;
alter table public.asset_usages      enable row level security;

commit;
