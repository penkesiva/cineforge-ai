-- Seed data for local development (`supabase db reset`). Owner: Workstream D.
-- Workstream D regenerates this file from packages/configurations via
-- scripts/generate_seed.py; do not hand-edit beyond the tenant row.

insert into public.tenants (id, name) values ('tenant_demo', 'CineForge Demo Studio')
on conflict (id) do nothing;
