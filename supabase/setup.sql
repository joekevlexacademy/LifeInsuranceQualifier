-- Life Insurance Qualifier — Supabase schema
-- Run this once in your Supabase SQL editor before deploying the app.

-- One row per installed GHL sub-account
create table if not exists installations (
  location_id    text primary key,
  agency_id      text not null default '',
  location_name  text,
  access_token   text not null,
  refresh_token  text not null,
  expires_at     timestamptz not null,
  installed_at   timestamptz not null default now(),
  uninstalled_at timestamptz
);

-- Custom field IDs and setup state per sub-account
create table if not exists location_config (
  location_id                  text primary key references installations(location_id),
  field_triage_state_id        text,
  field_product_direction_id   text,
  field_active_deps_id         text,
  field_coverage_amount_id     text,
  field_product_type_id        text,
  field_budget_id              text,
  field_urgency_id             text,
  field_occupation_id          text,
  field_height_id              text,
  field_weight_id              text,
  field_medications_id         text,
  field_existing_coverage_id   text,
  field_prior_outcome_id       text,
  field_underwriting_notes_id  text,
  setup_complete               boolean not null default false,
  setup_at                     timestamptz
);

-- Migration: add new field columns to existing location_config tables
alter table location_config add column if not exists field_budget_id             text;
alter table location_config add column if not exists field_urgency_id            text;
alter table location_config add column if not exists field_occupation_id         text;
alter table location_config add column if not exists field_height_id             text;
alter table location_config add column if not exists field_weight_id             text;
alter table location_config add column if not exists field_medications_id        text;
alter table location_config add column if not exists field_existing_coverage_id  text;
alter table location_config add column if not exists field_prior_outcome_id      text;
alter table location_config add column if not exists field_underwriting_notes_id text;

-- Lightweight qualification history for the sidebar home screen
create table if not exists qualifications (
  id            uuid primary key default gen_random_uuid(),
  location_id   text not null references installations(location_id),
  contact_id    text not null,
  contact_name  text,
  triage_state  text,
  qualified_at  timestamptz not null default now()
);

create index if not exists qualifications_location_time
  on qualifications(location_id, qualified_at desc);

-- Only the service role key (server-side) can access these tables.
-- No policies needed — RLS with zero policies denies all non-service-role access.
alter table installations   enable row level security;
alter table location_config enable row level security;
alter table qualifications  enable row level security;
