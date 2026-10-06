# Database Migrations Guide

FastKitty provides multi-tenancy-aware database migrations using [Alembic](https://alembic.sqlalchemy.org/) and async SQLAlchemy.

The migration runner dynamically adapts to your configured tenancy strategy (`row`, `schema`, or `database`).

---

## Quick Reference

| Task | Command |
|---|---|
| Apply all pending migrations | `uv run alembic upgrade head` |
| Migrate a single tenant | `uv run alembic -x tenant=tenant_1 upgrade head` |
| Generate raw SQL (offline preview) | `uv run alembic upgrade head --sql` |
| View current migration heads | `uv run alembic heads` |
| View migration history | `uv run alembic history` |
| Create a new migration revision | `uv run alembic revision -m "description"` |

---

## Multi-Tenancy Strategy Behaviors

FastKitty's migration runner in `db/migrations.py` (invoked via `alembic/env.py`) inspects `TENANCY_DB_STRATEGY`:

### 1. Row Strategy (`TENANCY_DB_STRATEGY=row`)
- Connects to the shared database URL.
- Migrates shared tables in the `public` schema.
- Tracks migration state in the shared `alembic_version` table.

### 2. Schema Strategy (`TENANCY_DB_STRATEGY=schema`)
- Connects to the shared database engine.
- Discovers active tenants from `TenancyConfigService`.
- For each tenant:
  1. Validates the schema name against SQL injection and reserved PostgreSQL schemas (`public`, `pg_catalog`, `information_schema`).
  2. Runs `CREATE SCHEMA IF NOT EXISTS "<schema_name>"`.
  3. Sets connection `search_path TO "<schema_name>", public`. (Note: Migrations include `public` so PostgreSQL extensions like `uuid-ossp` or `citext` installed in `public` remain accessible during DDL execution. In contrast, runtime query execution sets `search_path TO "<schema_name>"` strictly to prevent data leaks from unmigrated tables).
  4. Runs migrations with isolated version tracking (`version_table_schema="<schema_name>"`).
  5. Cleans up with `RESET search_path`.

> [!NOTE]
> FastKitty is primarily built and optimized for PostgreSQL. PostgreSQL natively supports isolated schemas within a database and dynamic `search_path` connection switching. In MySQL/MariaDB, `SCHEMA` is an exact alias for `DATABASE` (there are no sub-schemas inside a database), so MySQL users should choose either the `database` or `row` strategy.

### 3. Database Strategy (`TENANCY_DB_STRATEGY=database`)
- Discovers active tenants from `TenancyConfigService` and connection secrets from `TenancySecretsService`.
- Creates an independent async engine for each tenant database.
- Runs migrations and updates the `alembic_version` table in each database independently.

---

## Selective Tenant Migrations

To migrate or test a single tenant without running migrations across all tenants, pass the `-x tenant=<tenant_id>` argument:

```bash
uv run alembic -x tenant=tenant_1 upgrade head
```

---

## Offline Mode / SQL Generation

If your production environment requires change reviews or database administrator (DBA) approval before executing DDL, generate raw SQL using `--sql`:

```bash
uv run alembic upgrade head --sql > migration.sql
```

Alembic will emit the complete transactional DDL for your configured strategy without executing anything against the live databases.

---

## Adding New Models

To register a new SQLAlchemy model for migrations:

1. Define your model inheriting from `Base`, `TenantScopedModel`, or `TimestampedModel` in `models/`:
   ```python
   # models/orders.py
   from sqlalchemy import Integer, String
   from sqlalchemy.orm import Mapped, mapped_column
   from models.base import Base, TenantScopedModel, TimestampedModel


   class Order(TenantScopedModel, TimestampedModel, Base):
       __tablename__ = "orders"
       id: Mapped[int] = mapped_column(Integer, primary_key=True)
   ```

2. Re-export the model in `models/__init__.py`:
   ```python
   # models/__init__.py
   from models.base import Base, TenantScopedModel, TimestampedModel
   from models.posts import BlogPost
   from models.orders import Order

   __all__ = [
       "Base",
       "TenantScopedModel",
       "TimestampedModel",
       "BlogPost",
       "Order",
   ]
   ```

3. Create your migration revision:
   ```bash
   uv run alembic revision -m "create orders table"
   ```

---

## Important Architectural Limitations: Raw SQL Bypass

> [!WARNING]
> **Raw SQL & Core Bulk Statements Bypass ORM Tenant Isolation and Timestamp Hooks**
>
> FastKitty's automatic multi-tenancy protections and timestamp management are powered by SQLAlchemy ORM event listeners:
> 1. **Tenant Isolation**: In `row` strategy, the automatic `WHERE tenant_id = :current_tenant` filter is injected via ORM `with_loader_criteria`.
> 2. **`updated_at` Timestamps**: Automatic UTC timestamp updating is managed via the ORM `onupdate` attribute.
>
> If developers use **raw SQL queries** (`session.execute(text("..."))`) or **SQLAlchemy Core bulk statements** (`session.execute(update(Model)...)`), **these ORM hooks will NOT trigger**:
> - Raw SQL statements will bypass tenant filtering unless an explicit `WHERE tenant_id = :tenant_id` clause is manually included.
> - Core bulk updates will NOT automatically update the `updated_at` column.
>
> Always prefer standard ORM operations (`session.scalars()`, `session.get()`, `session.add()`) to preserve tenant isolation and audit timestamp guarantees.
