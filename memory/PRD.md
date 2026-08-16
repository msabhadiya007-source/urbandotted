# UrbanDotted SEO Intelligence Platform — PRD

## Original problem statement
Stage 1 Hardened Plan: an internal, Docker-portable SEO operations platform delivering
production read-only intelligence for AU + NZ across the full UrbanDotted Shopify catalogue
(45k+ products). Zero Shopify writes. Data model and policy engine ready for Stage 2 write
enablement. Full statement retained in the conversation history and encoded in the milestones
and acceptance tests below.

## Confirmed user decisions
1. **Data**: build connectors against the real Shopify Admin GraphQL / GSC BigQuery + Search
   Analytics contracts from day one; use seeded fixtures only through development adapters.
   Production builds must clearly identify DEMO vs LIVE and never silently fall back to demo.
   Real-data integration is mandatory before Stage 1 can be called complete.
2. **Database**: PostgreSQL 16 + Redis + BigQuery is the production target. MongoDB is a
   temporary development adapter behind a strict repository abstraction. Postgres migrations
   live in the repo from the start.
3. **LLM**: Claude Haiku 4.5 default for classification, escalating to Claude Sonnet 4.6 below
   the confidence threshold or for Tier A entities; GPT-5.4 Mini as fallback. Everything routed
   through a provider-agnostic `LLMRouter`; no model name in business logic.
4. **Screens**: core set first with real depth and drill-downs, not thin placeholders.
5. **Auth**: JWT email/password, single admin, RBAC schema ready for multi-admin.

## Architecture (as built)
- **Frontend**: React + Tailwind + shadcn/ui, React Router, TanStack Query, Recharts, sonner.
  Obsidian ops-console theme (IBM Plex Sans + JetBrains Mono, near-black surfaces, hairline
  borders, tabular numerics).
- **Backend**: FastAPI. `app/config.py` (DEMO vs LIVE modes), `app/repositories.py`
  (Repository interface + MongoRepository dev adapter + UnitOfWork), `app/sources.py`
  (`ShopifyCatalogSource`, `GSCDataSource` with Live/BigQuery/SearchAnalytics implementations),
  `app/services/` (audit, cost, policy, scoring, cannibalization, llm_router, jobs, pipelines,
  agents registry).
- **Production stack**: `/app/docker-compose.yml` (Postgres 16, Redis, MinIO, api, arq worker,
  web) and `/app/migrations/postgres/001_init.sql` (full relational schema, partitioned
  `gsc_performance`, append-only audit rules, `stage1_no_execution` CHECK constraint).

## Core requirements (static)
- Zero Shopify writes; no write route may exist in the API.
- Every recommendation must link to its evidence and the memory record behind it.
- Global $100/month paid-API ceiling with per-provider caps; fail closed at 100% for paid
  calls while free pipelines keep running.
- Append-only, hash-chained audit log covering every action and API call.
- AU + NZ active; US/UK/CA schema-ready but ingestion disabled.

## Implemented — 16 Jun 2026 (M1, M4, M6 slice + acceptance harness)
- JWT auth: login/logout/me/refresh, httpOnly cookies + Bearer, bcrypt, per-email and
  per-ip+email brute-force lockout (5 attempts / 15 min), RBAC permission matrix.
- Repository abstraction with the full Stage 1 relational domain; Postgres DDL committed.
- Shopify + GSC connectors written against real API contracts (cursor pagination, market
  webPresence detection, BigQuery `searchdata_url_impression` SQL, Search Analytics request
  body). `DEMO_INFRA_MODE` separation with no silent fallback; `/api/meta/mode` exposes the
  active adapter and what live config is missing.
- Deterministic services: opportunity scoring (0-100, five weighted components), dynamic
  A/B/C/D percentile tiering, cannibalization detection, anomaly detection, all runnable
  through an internal job abstraction (Redis/ARQ in production).
- `LLMRouter` with per-task budgets, token accounting into the cost ledger, response caching
  with revalidation dates and confidence-threshold escalation. Intent classification pipeline.
- `PolicyEngine`: GREEN/YELLOW/RED classes, all Shopify write actions compiled to DENY,
  proposals stored with previous_value/proposed_value/evidence, executor is a no-op logger.
- `CostLedger`: per-provider caps under a global ceiling, 50/75/90/100 alerts, cache-hit
  savings, blocked-call accounting, audited manual override, budget-exhaustion self-test.
- Hash-chained audit log with concurrency-safe sequencing and a `/api/audit/verify` endpoint.
- 28 logical agent roles (7 LLM, 21 deterministic services) surfaced in the UI and memory.
- Seeded AU + NZ development fixtures: 1,200 products, 2,400 market rows, 8 collections,
  1,856 keywords, ~9k GSC rows, technical issues, competitors, SERP snapshots, memory,
  decisions and cost history — every row tagged `data_mode: DEMO`.
- Screens: Login, Overview, AU War Room, NZ War Room, Opportunities (evidence drawer),
  Keywords/GSC (query drawer), Technical SEO (issue drawer), Cost, AI Operations
  (activity / roles / memory / proposed actions). Disabled backlog nav for the remaining five.
- Test harness: `/app/backend/tests/backend_test.py` — 39/39 passing, including the read-only
  invariant, budget-exhaustion and audit-chain acceptance tests.

## Backlog (prioritised)
**P0 — required for Stage 1 acceptance on real data**
1. Connect the real UrbanDotted Shopify store (read-only scopes) — full 45k cursor-paginated
   sync, webhooks, nightly reconciliation, `sync_runs` reporting.
2. Connect GSC: Search Analytics API bootstrap + BigQuery bulk export rollups; report the
   unmatched-URL rate when joining GSC URLs to the catalogue.
3. Deploy on the approved production stack (Postgres 16 + Redis + BigQuery + S3) and re-run
   every acceptance test against live data, including the restart-persistence test.
4. Real incremental crawler workers (politeness, change detection, S3 artifacts) replacing
   seeded crawl rows; PageSpeed CWV sampling under budget.
5. CI gate that fails the production build if any screen renders from fixtures.

**P1**
6. Products and Collections screens with full drill-downs.
7. Competitors screen + DataForSEO SERP integration and competitor delta explainer.
8. Approvals queue UI (read-only) and Experiments schema screen.
9. Keyword clusterer + DataForSEO expansion for Tier A only.
10. Notification channel decision (in-app only vs Resend email) for budget and regression alerts.

**P2**
11. Internal link graph and backlink diff surfaces.
12. Content outline/draft and outreach draft agents (stored, never published).
13. Multi-admin activation, US/UK/CA ingestion switch-on.

## Next tasks
- Confirm the hosting target (VPS / Fly.io / Render) so the BigQuery service account and
  outbound IP can be provisioned.
- Provide the Shopify read-only Admin API token and GSC service account when ready for M2.
- Decide the Stage 1 alert channel.
