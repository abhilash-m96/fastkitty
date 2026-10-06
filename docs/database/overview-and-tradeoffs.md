# The 3 Database Strategies & Tradeoffs

FastKitty supports three distinct multi-tenancy database strategies, controlled at startup via a single environment variable:

```env
TENANCY_DB_STRATEGY=database  # Options: database | schema | row
```

Choosing the right strategy depends on your isolation requirements, operational overhead, and budget:

| Strategy | Isolation Level | Infrastructure Cost | Operational Complexity | Best For |
|---|---|---|---|---|
| **`database`** | **Strongest** — Separate physical/logical DB per tenant | Highest — One connection pool per active tenant | Moderate — Managed via LRU cache, migrations run per DB | Enterprise SaaS, compliance (HIPAA, SOC2), noisy-neighbor avoidance |
| **`schema`** | **Strong** — PostgreSQL schema namespace (`search_path`) | Moderate — Shared DB cluster, shared connection pool | Low — Fast provisioning, isolated tables per tenant | Mid-stage SaaS, fast tenant onboarding, multi-brand portals |
| **`row`** | **Standard** — Shared table, ORM-enforced `tenant_id` filter | Lowest — Single DB, single schema, single connection pool | Lowest — Standard single-tenant database operations | Early-stage MVPs, B2C tenants, high tenant count with low per-tenant data |

---

## RDBMS Compatibility & Multi-Database Engine Support

FastKitty is built on **SQLAlchemy 2.0 async**, providing broad multi-database support with specific architectural tradeoffs:

| Database | Supported FastKitty Strategies | How Sub-Schemas Work & Compatibility Notes |
|---|---|---|
| **PostgreSQL** | **All (`database`, `schema`, `row`)** | **Primary Target**. Full native support for all 3 strategies. Includes dynamic `search_path` schema switching, async pooling via `asyncpg`, and automated multi-tenant Alembic migrations. |
| **MySQL / MariaDB** | **`database`, `row`** | In MySQL, **`DATABASE` and `SCHEMA` are exact synonyms** (`CREATE SCHEMA` is identical to `CREATE DATABASE`). There are no sub-schemas inside a MySQL database. Use either `database` strategy (separate MySQL databases) or `row` strategy. |
| **SQLite** | **`database`, `row`** | Single-file database. Supported for `database` (separate `.db` files per tenant) and `row` (single `.db` file with `tenant_id` column). No native sub-schemas. |
| **Microsoft SQL Server** | **`database`, `row`** | Full support for `database` and `row` strategies. While MSSQL supports schema namespaces (`tenant_1.table`), it lacks dynamic per-connection `search_path` switching without user credential changes. |
| **Oracle** | **`database`, `row`** | Full support for `database` and `row` strategies. In Oracle, a schema is synonymous with a database `USER`. |

---

## Single Server (Dev) vs. Multi-Cluster (Production)

In local development and Docker Compose, all logical databases (`tenant_1`, `tenant_2`, `fastkitty_shared`) and tenant schemas run inside a single PostgreSQL server container (`localhost:5432`) for convenience and zero-cost local setup.

However, because every tenant's `DatabaseConfig` independently defines `host`, `port`, `username`, `password`, and `database_name`:
- **In `database` strategy**: Tenants can be distributed across completely separate physical or cloud RDS clusters in different AWS/GCP regions (e.g. Tenant 1 on `eu-west-1.rds.amazonaws.com` and Tenant 2 on `us-east-1.rds.amazonaws.com`).
- **In `schema` strategy**: Tenants share a database cluster, isolated by schema namespaces.
- **In `row` strategy**: Tenants share a single database and schema with row-level tenant filtering.

> [!TIP]
> **Connecting to Remote & Managed Databases (TLS/SSL)**:  
> When connecting to managed cloud databases (such as AWS RDS, Aurora, GCP Cloud SQL, or Supabase), encrypted connections are typically required by default. You can simply add `"ssl": "require"` (or `true`) under `database_config` in your secrets configuration, or append `?ssl=require` directly to `database_uri`:
> ```json
> {
>   "host": "rds-host.amazonaws.com",
>   "port": 5432,
>   "username": "user",
>   "password": "secret",
>   "database_name": "dbname",
>   "ssl": "require"
> }
> ```
> FastKitty automatically configures the URI with the specified SSL mode, and `asyncpg` negotiates TLS encryption with the server.

---

## Guarantees & Known Limitations

### Strategy Guarantees

* **`database` strategy**: Strongest isolation. Tenant queries run against distinct physical or logical database instances. Cross-tenant leakage via application bugs is structurally impossible at the database engine level.
* **`schema` strategy**: Strong isolation via PostgreSQL schema namespaces. The `search_path` is dynamically set per transaction using `SET LOCAL search_path` on the `after_begin` event, cleanly reverting on transaction boundaries and preventing pooled connection leaks even across rollbacks.
* **`row` strategy**: FastKitty automatically injects tenant filters on all ORM queries and statements (`select`, `update`, `delete`) via `with_loader_criteria`, stamps `tenant_id` on inserts, and validates deleted instances in the session identity map.

### Known Limitations & Trade-offs

* **Raw SQL ORM Bypass (`row` strategy)**:  
  When running `TENANCY_DB_STRATEGY=row`, SQLAlchemy's `with_loader_criteria` intercepts only ORM-level queries (`select(Model)`, `session.scalars(...)`). If a developer executes **raw SQL** (`session.execute(text("SELECT * FROM blog_posts"))`), the ORM criteria hook is **bypassed**. In `row` strategy, raw SQL must include manual `WHERE tenant_id = :tenant_id` checks. In `database` and `schema` strategies, raw SQL is still fully tenant-isolated.
* **Engine Support & DDL Complexity (`schema` strategy)**:  
  Not all database engines support schemas (e.g. MySQL and SQLite lack true schema namespaces; in MySQL, `SCHEMA` is synonymous with `DATABASE`). Additionally, running schema migrations and DDL upgrades across hundreds of tenant schemas can become operationally complex and slow.
* **Resource & Infrastructure Costs (`database` strategy)**:  
  Dedicated physical or logical databases incur the highest infrastructure costs and connection pool resource consumption (managed via LRU cache). Tenants can be separate physical/managed database servers OR separate logical databases within the same server.
