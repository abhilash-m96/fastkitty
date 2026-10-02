# Feature Plan: Multi-Tenant Database Migrations

## Chunks
- [ ] feat/alembic-foundation — Add alembic dependency, explicit model re-exports in models/__init__.py, alembic.ini, and base migration for BlogPost
- [ ] feat/multi-tenant-migrations — Multi-strategy migration runner in alembic/env.py supporting row, schema, and database isolation modes
- [ ] feat/migration-tests — Integration and unit tests verifying migrations and schema/database isolation across all three strategies
- [ ] docs/migration-guide — Migration operational guide, CLI examples, and README callouts for raw SQL limitations

## Stack Hierarchy
feat/alembic-foundation -> epic-configurable-db-strategy
feat/multi-tenant-migrations -> feat/alembic-foundation
feat/migration-tests -> feat/multi-tenant-migrations
docs/migration-guide -> feat/migration-tests
