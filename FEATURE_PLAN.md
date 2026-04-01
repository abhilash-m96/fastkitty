# Feature Plan: Async Tenancy DB Strategy Selection

## Chunks
- [x] feat/async-db-foundation — Replace sync engine/session setup with SQLAlchemy async engine and async_sessionmaker; add FastAPI lifespan startup/shutdown wiring; switch the example app's DB-facing codepaths to async foundations only
- [ ] feat/strategy-config — Add TENANCY_DB_STRATEGY and strategy-aware schema/config changes, including schema_name on tenant DB config; validate startup wiring and payload shape for the selected strategy only
- [ ] feat/db-strategy-interface — Introduce the internal async tenancy strategy contract, tenant DB context object, app-state strategy selection, and request-scoped session acquisition interface
- [ ] feat/database-strategy — Implement database-per-tenant using one async engine per resolved tenant DB URL, bounded engine caching, eviction disposal, and isolated session/pool handling
- [ ] feat/schema-strategy — Implement schema-per-tenant using a shared async engine plus per-session schema switching and explicit schema-state reset before pooled connection reuse
- [ ] feat/row-strategy — Implement row-per-tenant using a shared async engine, a tenant-aware declarative base that adds tenant_id, created_at, and updated_at, automatic tenant stamping on writes, and enforced tenant scoping on ORM reads
- [ ] feat/dependency-wiring — Refactor FastAPI DB dependencies to resolve TenantContext once, acquire sessions through the selected strategy, and keep strategy details out of route and service dependency signatures
- [ ] feat/tests — Convert DB/route/service tests to async patterns and add strategy-specific coverage for isolation, leakage prevention, and eviction behavior
- [ ] docs/strategy-guide — Update README and setup docs for async-only usage, per-strategy configuration, safety guarantees, and strategy-selection behavior

## Stack Hierarchy
feat/async-db-foundation -> main
feat/strategy-config -> feat/async-db-foundation
feat/db-strategy-interface -> feat/strategy-config
feat/database-strategy -> feat/db-strategy-interface
feat/schema-strategy -> feat/database-strategy
feat/row-strategy -> feat/schema-strategy
feat/dependency-wiring -> feat/row-strategy
feat/tests -> feat/dependency-wiring
docs/strategy-guide -> feat/tests
