-- UrbanDotted SEO Intelligence Platform — Stage 1 production schema (PostgreSQL 16).
-- The Mongo adapter used in the Emergent development environment mirrors these tables 1:1.
-- Stage 1 is read-only: no table grants any Shopify write path.

CREATE TYPE market_code AS ENUM ('AU', 'NZ', 'US', 'UK', 'CA');
CREATE TYPE tier_code AS ENUM ('A', 'B', 'C', 'D');
CREATE TYPE risk_class AS ENUM ('GREEN', 'YELLOW', 'RED');
CREATE TYPE entity_kind AS ENUM ('product', 'collection', 'page', 'keyword');
CREATE TYPE search_intent AS ENUM ('transactional', 'commercial', 'informational', 'navigational');
CREATE TYPE severity_level AS ENUM ('critical', 'high', 'medium', 'low');

CREATE TABLE users (
  id            BIGSERIAL PRIMARY KEY,
  email         CITEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name          TEXT,
  role          TEXT NOT NULL DEFAULT 'viewer',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE products (
  id                BIGSERIAL PRIMARY KEY,
  shopify_id        TEXT UNIQUE NOT NULL,
  handle            TEXT UNIQUE NOT NULL,
  title             TEXT NOT NULL,
  product_type      TEXT,
  vendor            TEXT,
  collection_handle TEXT,
  status            TEXT,
  seo_title         TEXT,
  seo_description   TEXT,
  description_words INT,
  image_count       INT,
  variant_count     INT,
  vertical          TEXT DEFAULT 'homeware',  -- clothing supported, not populated in Stage 1
  data_mode         TEXT NOT NULL DEFAULT 'LIVE',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE product_variants (
  id                 BIGSERIAL PRIMARY KEY,
  product_id         BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  shopify_id         TEXT UNIQUE NOT NULL,
  sku                TEXT,
  price              NUMERIC(12,2),
  inventory_quantity INT,
  available          BOOLEAN
);

CREATE TABLE product_market (
  id                 BIGSERIAL PRIMARY KEY,
  product_id         BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  market             market_code NOT NULL,
  url                TEXT NOT NULL,
  price              NUMERIC(12,2),
  currency           TEXT,
  available          BOOLEAN,
  inventory_quantity INT,
  published          BOOLEAN,
  hreflang           TEXT,
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (product_id, market)
);

CREATE TABLE collections (
  id              BIGSERIAL PRIMARY KEY,
  shopify_id      TEXT UNIQUE NOT NULL,
  handle          TEXT UNIQUE NOT NULL,
  title           TEXT NOT NULL,
  seo_title       TEXT,
  seo_description TEXT,
  product_count   INT,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE pages (
  id            BIGSERIAL PRIMARY KEY,
  url           TEXT NOT NULL,
  page_type     TEXT NOT NULL,
  entity_handle TEXT,
  title         TEXT,
  UNIQUE (url)
);

CREATE TABLE page_market (
  id                TEXT,
  page_id           BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  market            market_code NOT NULL,
  indexable         BOOLEAN,
  canonical_url     TEXT,
  hreflang_complete BOOLEAN,
  in_sitemap        BOOLEAN,
  status_code       INT,
  lcp_ms            INT,
  cls               NUMERIC(6,3),
  inp_ms            INT,
  last_crawled_at   TIMESTAMPTZ,
  PRIMARY KEY (page_id, market)
);

CREATE TABLE keywords (
  id                BIGSERIAL PRIMARY KEY,
  query             TEXT NOT NULL,
  market            market_code NOT NULL,
  preferred_url     TEXT,
  preferred_page_type TEXT,
  category          TEXT,
  cluster           TEXT,
  intent            search_intent,
  intent_confidence NUMERIC(4,3),
  intent_method     TEXT,
  intent_reasoning  TEXT,
  impressions_30d   BIGINT,
  avg_position      NUMERIC(6,2),
  source            TEXT,
  expansion_provider TEXT,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (query, market)
);

-- Nightly materialised rollup from BigQuery bulk export.
CREATE TABLE gsc_performance (
  id             BIGSERIAL PRIMARY KEY,
  url            TEXT NOT NULL,
  query          TEXT NOT NULL,
  market         market_code NOT NULL,
  country        TEXT NOT NULL,
  device         TEXT NOT NULL,
  page_type      TEXT,
  impressions    BIGINT NOT NULL,
  clicks         BIGINT NOT NULL,
  position       NUMERIC(6,2) NOT NULL,
  prev_impressions BIGINT,
  prev_clicks    BIGINT,
  prev_position  NUMERIC(6,2),
  period_start   DATE NOT NULL,
  period_end     DATE NOT NULL,
  ingested_via   TEXT NOT NULL
) PARTITION BY RANGE (period_end);

CREATE INDEX ON gsc_performance (market, query);
CREATE INDEX ON gsc_performance (url, market);

CREATE TABLE opportunity_scores (
  id                 BIGSERIAL PRIMARY KEY,
  entity_type        entity_kind NOT NULL,
  entity_id          TEXT NOT NULL,
  entity_label       TEXT,
  market             market_code NOT NULL,
  score              NUMERIC(5,1) NOT NULL,
  tier               tier_code NOT NULL,
  rank               INT,
  percentile         NUMERIC(5,1),
  components         JSONB NOT NULL,
  weights            JSONB NOT NULL,
  evidence           JSONB NOT NULL,
  intent             search_intent,
  confidence         NUMERIC(4,3),
  recommended_action TEXT,
  preferred_url      TEXT,
  computed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (entity_type, entity_id, market)
);
CREATE INDEX ON opportunity_scores (market, score DESC);

CREATE TABLE rank_history (
  id          BIGSERIAL PRIMARY KEY,
  keyword_id  BIGINT NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
  market      market_code NOT NULL,
  device      TEXT NOT NULL,
  position    NUMERIC(6,2) NOT NULL,
  captured_on DATE NOT NULL,
  UNIQUE (keyword_id, market, device, captured_on)
);

CREATE TABLE technical_issues (
  id                BIGSERIAL PRIMARY KEY,
  issue_type        TEXT NOT NULL,
  severity          severity_level NOT NULL,
  "group"           TEXT NOT NULL,
  description       TEXT,
  url               TEXT NOT NULL,
  market            market_code NOT NULL,
  page_type         TEXT,
  status            TEXT NOT NULL DEFAULT 'open',
  detected_by       TEXT,
  evidence          JSONB,
  first_detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON technical_issues (severity, status);

CREATE TABLE cannibalization (
  id                     BIGSERIAL PRIMARY KEY,
  query                  TEXT NOT NULL,
  market                 market_code NOT NULL,
  primary_url            TEXT NOT NULL,
  competing_urls         JSONB NOT NULL,
  total_impressions      BIGINT,
  rival_impression_share NUMERIC(5,3),
  severity               severity_level,
  verdict                TEXT,
  resolution_method      TEXT,
  evidence               JSONB,
  detected_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (query, market)
);

CREATE TABLE competitors (
  id                  BIGSERIAL PRIMARY KEY,
  domain              TEXT NOT NULL,
  market              market_code NOT NULL,
  visibility_share    NUMERIC(6,2),
  share_delta_30d     NUMERIC(6,2),
  queries_overlapping INT,
  avg_position        NUMERIC(6,2),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (domain, market)
);

CREATE TABLE serp_snapshots (
  id          BIGSERIAL PRIMARY KEY,
  query       TEXT NOT NULL,
  market      market_code NOT NULL,
  device      TEXT NOT NULL,
  results     JSONB NOT NULL,
  provider    TEXT NOT NULL,
  artifact_s3_key TEXT,
  cost_usd    NUMERIC(10,6),
  budget_gate TEXT,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_roles (
  key         TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL,   -- 'llm' | 'service'
  "group"     TEXT NOT NULL,
  description TEXT,
  model_tier  TEXT
);

CREATE TABLE agent_activity (
  id            BIGSERIAL PRIMARY KEY,
  agent_role    TEXT NOT NULL REFERENCES agent_roles(key),
  job           TEXT NOT NULL,
  status        TEXT NOT NULL,
  actor         TEXT,
  params        JSONB,
  result        JSONB,
  error         TEXT,
  queue_backend TEXT,
  started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  duration_ms   INT
);
CREATE INDEX ON agent_activity (started_at DESC);

CREATE TABLE agent_memories (
  id          BIGSERIAL PRIMARY KEY,
  memory_type TEXT NOT NULL,   -- business | seo_knowledge | failure | decision | llm_cache
  title       TEXT NOT NULL,
  content     TEXT,
  agent_role  TEXT,
  confidence  NUMERIC(4,3) NOT NULL,
  sample_size INT NOT NULL DEFAULT 0,
  evidence    JSONB,
  status      TEXT NOT NULL DEFAULT 'active',
  task        TEXT,
  cache_key   TEXT,
  result      JSONB,
  model       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  recheck_at  TIMESTAMPTZ,
  revalidate_at TIMESTAMPTZ
);
CREATE INDEX ON agent_memories (memory_type, confidence DESC);

CREATE TABLE decisions (
  id         BIGSERIAL PRIMARY KEY,
  title      TEXT NOT NULL,
  rationale  TEXT,
  outcome    TEXT,
  decided_by TEXT,
  evidence   JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE seo_actions (
  id                        BIGSERIAL PRIMARY KEY,
  action_type               TEXT NOT NULL,
  entity_type               TEXT NOT NULL,
  entity_id                 TEXT NOT NULL,
  previous_value            JSONB,
  proposed_value            JSONB,
  evidence                  JSONB NOT NULL,
  rationale                 TEXT,
  risk_class                risk_class NOT NULL,
  approver_required         BOOLEAN NOT NULL DEFAULT TRUE,
  policy_decision           TEXT NOT NULL,
  status                    TEXT NOT NULL,
  proposed_by               TEXT,
  executed                  BOOLEAN NOT NULL DEFAULT FALSE,
  execution_note            TEXT,
  previous_value_snapshot_at TIMESTAMPTZ,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Stage 1 hard guarantee, enforced by the database itself.
  CONSTRAINT stage1_no_execution CHECK (executed = FALSE)
);

CREATE TABLE experiments (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL,
  hypothesis   TEXT,
  status       TEXT NOT NULL DEFAULT 'SCHEMA_ONLY_STAGE_1',
  market       market_code,
  metric       TEXT,
  control_size INT,
  variant_size INT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only, hash-chained per UTC day.
CREATE TABLE audit_log (
  id          BIGSERIAL PRIMARY KEY,
  chain_day   DATE NOT NULL,
  seq         BIGINT NOT NULL,
  actor       TEXT NOT NULL,
  actor_role  TEXT,
  action      TEXT NOT NULL,
  entity_type TEXT,
  entity_id   TEXT,
  method      TEXT,
  path        TEXT,
  status      INT,
  metadata    JSONB,
  prev_hash   CHAR(64) NOT NULL,
  entry_hash  CHAR(64) NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (chain_day, seq)
);
CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;

CREATE TABLE budgets (
  month          CHAR(7) PRIMARY KEY,
  global_cap_usd NUMERIC(10,2) NOT NULL,
  provider_caps  JSONB NOT NULL,
  overrides      JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cost_ledger (
  id         BIGSERIAL PRIMARY KEY,
  month      CHAR(7) NOT NULL,
  provider   TEXT NOT NULL,
  operation  TEXT NOT NULL,
  agent_role TEXT,
  model      TEXT,
  cost_usd   NUMERIC(12,6) NOT NULL,
  tokens_in  INT NOT NULL DEFAULT 0,
  tokens_out INT NOT NULL DEFAULT 0,
  status     TEXT NOT NULL,          -- charged | blocked | cache_hit
  reason     TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON cost_ledger (month, provider);

CREATE TABLE sync_runs (
  id          BIGSERIAL PRIMARY KEY,
  kind        TEXT NOT NULL,
  products    INT,
  collections INT,
  markets     TEXT[],
  status      TEXT,
  note        TEXT,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);
