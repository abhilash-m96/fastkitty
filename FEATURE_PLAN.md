# Feature Plan: Multi-Tenant Database Migrations

## Chunks
- [x] feat/alembic-foundation — Add alembic dependency, explicit model re-exports in models/__init__.py, alembic.ini, and async migration scaffolding
- [x] feat/multi-tenant-migrations — Multi-strategy migration runner in alembic/env.py supporting row, schema, and database isolation modes with -x tenant=... filtering
- [x] feat/blog-posts-migration — Initial migration for BlogPost, multi-strategy test coverage, migration guide, and README documentation links

## Stack Hierarchy
feat/alembic-foundation -> epic-configurable-db-strategy
feat/multi-tenant-migrations -> feat/alembic-foundation
feat/blog-posts-migration -> feat/multi-tenant-migrations
