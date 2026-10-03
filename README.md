# fastkit(ty) 🐱

![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688)
![License](https://img.shields.io/github/license/abhilash-m96/fastkitty)
![Stars](https://img.shields.io/github/stars/abhilash-m96/fastkitty?style=social)

Ever needed to disable a feature for one customer but enable it for another?
Give one tenant unlimited API access and another a restricted workflow?
Make your service behave differently depending on which tenant is calling?

That's multi-tenant SaaS — and fastkit(ty) 🐱 is a FastAPI template built for it.

A pragmatic foundation for building multi-tenant services with explicit tenant context, clear dependency boundaries, and a service-first architecture.

Tenant awareness flows through your application — not hidden in globals or middleware — so your business logic stays predictable, testable, and easy to evolve.

Tenancy, feature flags, database strategy, config, secrets, and identity are all pluggable and cleanly separated, letting you adapt your model without rewriting your core business logic.

---

## Why this template

- **Focus on business logic** — Tenancy, config, secrets, identity, and database wiring are handled for you. Configure what you need and build what matters.
- **Flexible by design** — Swap config or secrets providers, or plug in your own, without touching core business logic.
- **Explicit over magic** — Tenant context flows through dependencies you can read, trace, and test. Nothing hidden.
- **Service-first architecture** — A clean service layer that can be exposed via HTTP, CLI, or other interfaces.
- **Built to evolve** — Start with a shared database, then move to schema-per-tenant or database-per-tenant as your needs grow.

---

## What you get

- Explicit tenancy via `X-Tenant-ID`
- Three DB strategies for multi-tenancy (database, schema, row)
- Clean dependency injection (tenancy, DB, identity)
- Service layer pattern (thin HTTP routes)
- Configurable identity provider (headers or JWT)
- Per-tenant feature configuration
- Extensible config and secrets providers
- Example CRUD service and routes

---

## Quickstart

### Option A: Local Development with Docker PostgreSQL (Recommended)

**1. Start the PostgreSQL service (with multi-tenant databases pre-configured)**

```bash
docker compose up -d postgres
```
This starts PostgreSQL 16 on `localhost:5432` and automatically runs [`docker/init-db.sh`](docker/init-db.sh) to create `tenant_1`, `tenant_2`, and `fastkitty_shared` databases.

**2. Install dependencies & create environment file**

```bash
uv sync
cp .env.example .env
```

**3. Run database migrations**

```bash
uv run alembic upgrade head
```

**4. Run the API with auto-reload**

```bash
uv run uvicorn main:app --reload
```

---

### Option B: Full Containerized Stack

To run both PostgreSQL and the FastKitty API containerized:

```bash
docker compose up --build -d
```
PostgreSQL boots, tenant databases are created, migrations run automatically on startup, and the API is live at `http://localhost:8000` with code reload.

**4. Try it — same endpoint, different tenants**

```bash
curl -X 'GET' \
  'http://127.0.0.1:8000/v1/hello' \
  -H 'accept: application/json' \
  -H 'X-Tenant-ID: tenant_1'
```

```json
{ "message": "Hello, welcome 'Tenant One'!" }
```

```bash
curl -X 'GET' \
  'http://127.0.0.1:8000/v1/hello' \
  -H 'accept: application/json' \
  -H 'X-Tenant-ID: tenant_2'
```

```json
{ "message": "Hi 'Tenant Two', welcome!" }
```

Same endpoint. Same route handler. Different tenant config.

**5. Here's the config driving it**

```json
{
  "tenant_1": {
    "tenant_id": "tenant_1",
    "display_name": "Tenant One",
    "is_active": true,
    "features": {
      "greet": {
        "message": "Hello, welcome '{tenant_name}'!"
      }
    }
  },
  "tenant_2": {
    "tenant_id": "tenant_2",
    "display_name": "Tenant Two",
    "is_active": true,
    "features": {
      "greet": {
        "message": "Hi '{tenant_name}', welcome!"
      }
    }
  }
}
```

**6. And the route**

```python
@router.get("/hello", name="greet")
async def hello(
    tenant_config: TenantConfig = Depends(get_tenant_config),
    feature_config: FeatureConfig | None = Depends(get_feature_config("greet")),
):
    message = feature_config.get("message") if feature_config else None
    tenant_name = tenant_config.display_name
    if not message:
        message = f"Hello {tenant_name}!"
    try:
        message = message.format(tenant_name=tenant_config.display_name)
    except (KeyError, ValueError):
        pass

    return {"message": message}
```

The route didn't change. The tenant config did. That's the fastkit(ty) model.

Open docs (dev only): `http://localhost:8000/docs`

---

## Architecture & Design Philosophy

fastkit(ty) is built around a small set of explicit opinions. They are worth understanding before you extend the template.

**Tenancy is infrastructure, not business logic**

Routes and services never know which DB strategy is active. They receive a session, query it, and return results. Whether that session points to a dedicated database, a schema-scoped connection, or a row-filtered shared pool is decided at startup and invisible above the dependency layer. This means your business logic doesn't change when you change your tenancy model.

**Tenant context is explicit, not ambient**

Tenant identity flows through FastAPI's dependency injection — you can see it, trace it, and test it. There are no thread-locals, no request-scoped globals, no middleware that silently injects context. If a route needs tenant context, it declares it. If it doesn't, it doesn't.

**Fail fast at startup**

Misconfiguration surfaces before traffic hits. The selected DB strategy is validated against all discoverable tenant secrets at startup. A tenant with a missing `schema_name` in schema mode, or a conflicting DB URL in row mode, raises immediately — not on the first request from that tenant.

**Auth is a peer concern, not a template concern**

fastkit(ty) is intentionally auth-agnostic. Auth belongs upstream — in a gateway or dedicated auth service — not inside a multi-tenant service template. By the time a request reaches your service, auth is already done. The template reads already-validated identity from incoming requests via `USER_DATA_SOURCE`. It does not validate or issue tokens.

**Config and secrets are provider-agnostic**

The template ships with file-based providers for local development and HashiCorp Vault/Consul adapters for production. Swapping providers requires no changes to business logic — only config.

**Services own business logic**

HTTP routes are thin. They resolve dependencies, call a service method, and return a response. Business logic lives in `services/` where it can be tested without an HTTP client and reused across interfaces.

---

## Project Layout

```
api/routes      HTTP routes
api/deps        dependency wiring (tenancy, db, user data)
services        business logic
models          SQLAlchemy models
schemas         Pydantic schemas
config          config providers and settings
db              database session and engine setup
```

---

## Configuration

The full list of settings is in `.env.example`. Key settings:

| Setting | Values | Description |
|---|---|---|
| `TENANCY_CONFIG_CONNECTION` | JSON | Config provider connection |
| `TENANCY_SECRETS_CONNECTION` | JSON | Secrets provider connection |
| `TENANCY_DB_STRATEGY` | `database` \| `schema` \| `row` | DB isolation strategy |
| `TENANCY_DATABASE_MAX_ENGINES` | int | Max cached engines for `database` strategy |
| `USER_DATA_SOURCE` | `header` \| `jwt` \| `claims` | Identity provider |

---

## Tenancy Model

Tenancy is resolved from the `X-Tenant-ID` header on every request.

- `tenants_config.json` defines tenants, their active status, and per-tenant feature config
- `tenants_secrets.json` provides DB connection details per tenant
- The app validates the selected DB strategy at startup and fails fast on incompatible tenant payloads

Tenant lookup and active checks are split into separate dependencies so you can apply them at different granularities:

```python
# enforce at router level — all routes in this router require an active tenant
router = APIRouter(dependencies=[Depends(require_active_tenant)])

# or at individual route level
@router.get("/hello", dependencies=[Depends(require_active_tenant)])
async def hello(): ...
```

Missing `X-Tenant-ID` returns 400. Unknown tenant returns 404. Inactive tenant returns 403.

---

## Database Strategy

### Choosing a Strategy

The right strategy depends on your isolation requirements and scale. This is a startup decision — there is no per-request strategy switching.

| Strategy | Isolation | Cost | Best for |
|---|---|---|---|
| `database` | Strongest — separate DB per tenant | Highest — one connection pool per tenant | Enterprise SaaS, strict data residency requirements |
| `schema` | Strong — PostgreSQL schema boundary | Moderate — one shared pool | Mid-stage products, regulatory requirements |
| `row` | Weakest — column filter only | Lowest — one pool, one schema | B2C products, large tenant counts, cost-sensitive |

Start with `row` if you are early stage. The template is designed so you can migrate to `schema` or `database` by changing one env var and updating your secrets — your routes and services change nothing.

### RDBMS Compatibility: Why FastKitty is Built Primarily for PostgreSQL

FastKitty is **primarily built and optimized for PostgreSQL**. While SQL syntax is broadly similar across engines, the concept and implementation of a "schema" differs fundamentally across relational databases:

| Database | Sub-Schema Support within a DB | How it Works & Compatibility with FastKitty |
|---|---|---|
| **PostgreSQL** | **Native First-Class** | **Full Support (Primary Target)**. A single database instance can hold many isolated schemas. Dynamic session switching via `SET search_path TO <schema>, public` provides lightweight, fast schema isolation with shared connection pooling. FastKitty's async driver (`asyncpg`) and migration runner are built for PostgreSQL. |
| **MySQL / MariaDB** | **No Sub-Schemas** | In MySQL, **`DATABASE` and `SCHEMA` are synonyms**. Executing `CREATE SCHEMA tenant_1` is identical to `CREATE DATABASE tenant_1`. MySQL has no concept of schemas *inside* a database. If using MySQL, developers must use either the **`database`** strategy (separate MySQL databases) or the **`row`** strategy. |
| **Oracle** | **Tied to Users** | In Oracle, a schema is synonymous with a database `USER`. Switching schemas dynamically requires `ALTER SESSION SET CURRENT_SCHEMA = tenant_1`. |
| **Microsoft SQL Server** | **Namespaces Only** | Schemas exist within a database (`tenant_1.table`), but lack dynamic session-level `search_path` switching without user credential changes. |
| **SQLite** | **File-Based** | Single-file database without native schema namespaces (unless attaching files). |

> [!NOTE]
> **Single Database Server (Dev) vs. Multi-Server / Multi-Cluster (Production)**
> In local development and Docker Compose, all logical databases (`tenant_1`, `tenant_2`, `fastkitty_shared`) and tenant schemas run inside a single PostgreSQL server container (`localhost:5432`) for convenience and zero-cost local setup.
>
> However, because every tenant's `DatabaseConfig` independently defines `host`, `port`, `username`, `password`, and `database_name`:
> - **In `database` strategy**: Tenants can be distributed across completely separate physical or cloud RDS clusters in different AWS/GCP regions (e.g. Tenant 1 on `eu-west-1.rds.amazonaws.com` and Tenant 2 on `us-east-1.rds.amazonaws.com`).
> - **In `schema` strategy**: Tenants share a database cluster, isolated by schema namespaces.
> - **In `row` strategy**: Tenants share a single database and schema with row-level tenant filtering.

### Configuring a Strategy

Set the strategy once in your env:

```env
TENANCY_DB_STRATEGY=schema
```

The DB layer is async-only. All connections use `AsyncSession` and require an async-compatible driver:

```
postgresql+asyncpg://...
```

**Database strategy — secret shape**

Each tenant provides its own DB URL:

```json
{
  "tenant_1": {
    "tenant_id": "tenant_1",
    "database_config": {
      "database_uri": "postgresql+asyncpg://tenant1_user:password@db.tenant1.com:5432/tenant1_db",
      "host": "db.tenant1.com",
      "port": 5432,
      "username": "tenant1_user",
      "password": "password",
      "database_name": "tenant1_db"
    }
  }
}
```

**Schema strategy — secret shape**

All tenants share one DB URL. Each tenant provides a `schema_name`:

```json
{
  "tenant_1": {
    "tenant_id": "tenant_1",
    "database_config": {
      "database_uri": "postgresql+asyncpg://shared_user:password@db.shared.com:5432/app_db",
      "host": "db.shared.com",
      "port": 5432,
      "username": "shared_user",
      "password": "password",
      "database_name": "app_db",
      "schema_name": "tenant_one"
    }
  }
}
```

**Row strategy — secret shape**

All tenants share one DB URL. No `schema_name` needed:

```json
{
  "tenant_1": {
    "tenant_id": "tenant_1",
    "database_config": {
      "database_uri": "postgresql+asyncpg://shared_user:password@db.shared.com:5432/app_db",
      "host": "db.shared.com",
      "port": 5432,
      "username": "shared_user",
      "password": "password",
      "database_name": "app_db"
    }
  }
}
```

### How it works under the hood

**Database strategy** caches engines per DB URL in a bounded LRU registry (`TENANCY_DATABASE_MAX_ENGINES`, default 50). When the limit is exceeded, the least recently used engine is evicted and disposed after all in-flight sessions on that engine finish — it will not force-close active connections.

**Schema strategy** sets `search_path` to `<schema>, public` at the start of every session and resets it before the connection is returned to the pool. The reset runs unconditionally even if the session raises — a broken connection during reset still closes the session cleanly.

**Row strategy** hooks SQLAlchemy's ORM event system per session. Reads get an automatic `WHERE tenant_id = :current_tenant` filter injected. Writes stamp new objects with `tenant_id` and guard against cross-tenant mutations before flush.

### Strategy Guarantees

- Missing `X-Tenant-ID` fails before a DB session is ever opened
- Inactive tenants are rejected before a DB session is ever opened
- Schema names are validated as safe SQL identifiers before use in `SET search_path`
- Reserved PostgreSQL schema names (`public`, `pg_catalog`, `information_schema`) are rejected even if they pass the identifier check
- Schema strategy resets `search_path` before the connection is returned to the pool
- Schema strategy closes the session cleanly even if `RESET search_path` itself raises
- Row strategy raises immediately if DB access is attempted without tenant context
- Row strategy raises before flush if a cross-tenant write is detected
- Database strategy never shares sessions across tenant DB URLs
- Evicted engines wait for in-flight sessions to finish before disposal, with a timeout to prevent indefinite blocking on stuck sessions

### Known Limitations

**Row strategy — ORM bypass**

The automatic tenant filter only applies to ORM-level queries. Raw SQL and Core-style bulk statements bypass it entirely:

```python
# these bypass the tenant filter — do not use on tenant-scoped tables
await session.execute(text("SELECT * FROM posts"))
await session.execute(update(Post).values(title="..."))
```

For raw SQL against tenant-scoped tables, always include an explicit `WHERE tenant_id = :tid` clause. This is a documented limitation, not a planned fix — the ORM path covers the common case and the escape hatch is documented so developers know where the boundary is.

**`updated_at` on bulk updates and raw SQL**

The `onupdate` hook on `TimestampedModel.updated_at` fires for ORM-tracked updates only. Core-level bulk updates and raw SQL bypass SQLAlchemy's ORM event cycle and will not automatically update `updated_at` or enforce `tenant_id` scoping. If you execute raw SQL or bulk statements, you must explicitly manage timestamps and tenant isolation in your SQL statements.

**Pool config conflicts in database strategy**

Two tenants pointing to the same DB URL share one engine. If their secrets specify different pool settings (e.g. different `pool_size`), the second tenant's first request will raise a `ValueError`. Ensure all tenants sharing a DB URL agree on pool configuration.

---

## Database Migrations

FastKitty includes multi-tenancy-aware database migrations using [Alembic](https://alembic.sqlalchemy.org/) and async SQLAlchemy (`asyncpg`). Migrations dynamically adapt to the active `TENANCY_DB_STRATEGY`:
- **`row` strategy**: Migrates shared tables in the `public` schema.
- **`schema` strategy**: Discovers active tenants, creates schemas if needed, sets `search_path`, and runs migrations with isolated version tracking per tenant schema.
- **`database` strategy**: Resolves tenant database URIs and runs migrations across isolated tenant databases independently.

Quick CLI usage:
```bash
# Run migrations across all active tenants
uv run alembic upgrade head

# Run migrations for a specific tenant
uv run alembic -x tenant=tenant_1 upgrade head

# Generate raw SQL preview (offline mode)
uv run alembic upgrade head --sql
```

For the comprehensive guide, strategy behaviors, and model registration instructions, see the [Database Migrations Guide](docs/migrations.md).

---

## Model Mixins

fastkit(ty) ships two independent SQLAlchemy mixins in `models/base.py`. They are intentionally separate so models opt into each explicitly.

**`TenantScopedModel`** adds a `tenant_id` column. Required for row strategy — the ORM hooks key off this mixin. Also useful in database and schema strategies for portability (switching strategies without changing models).

**`TimestampedModel`** adds `created_at` and `updated_at` columns with server-side UTC defaults.

Models that need both inherit from both explicitly:

```python
from models.base import TenantScopedModel, TimestampedModel

# tenant-scoped with timestamps — the common case
class BlogPost(TenantScopedModel, TimestampedModel):
    __tablename__ = "blog_posts"
    # your fields here

# timestamps only — for non-tenant tables like audit logs
class AuditLog(TimestampedModel):
    __tablename__ = "audit_logs"
    # your fields here
```

The explicit multiple inheritance is intentional. A model that is tenant-scoped doesn't automatically need timestamps and vice versa. Composing them explicitly makes the intent clear.

---

## Config Providers

Config providers supply per-tenant configuration: tenant ID, display name, active status, and feature flags.

### Currently Supported

**`file`** (default) — reads from a local JSON file. Zero dependencies, ideal for local development and testing.

```json
TENANCY_CONFIG_CONNECTION={"type": "file", "path": "tenants_config.json"}
```

**`hc_consul`** — reads from HashiCorp Consul. Tenant configs are stored as KV entries under a configurable prefix.

```json
TENANCY_CONFIG_CONNECTION={"type": "hc_consul", "host": "consul.internal", "port": 8500, "consul_prefix": "tenants/config"}
```

### How to Add a New Config Provider

1. Implement a new `TenancyConfigProvider` in `config/tenancy_providers.py`. The interface requires `get_tenant(tenant_id)` and optionally `get_tenants()` for startup validation.

2. Add a connection model in `config/settings.py`:

```python
class TenancyConfigFooConnection(BaseModel):
    type: Literal["foo"]
    # your connection fields
```

Include it in the `TenancyConfigConnection` union.

3. Register it in `config/tenancy_providers_factory.py`:

```python
if connection.type == "foo":
    return FooConfigProvider(connection)
```

4. Set `TENANCY_CONFIG_CONNECTION` in `.env` with `"type": "foo"` and your connection fields.

> If your provider does not support listing all tenants (e.g. it only supports point lookups), implement `get_tenants()` to raise `NotImplementedError`. Startup validation will be skipped with a warning log — it cannot iterate what it cannot list.

---

## Secrets Providers

Secrets providers supply per-tenant DB connection details — credentials, host, port, strategy-specific fields like `schema_name`.

### Currently Supported

**`file`** (default) — reads from a local JSON file. Zero dependencies, ideal for local development and testing.

```json
TENANCY_SECRETS_CONNECTION={"type": "file", "path": "tenants_secrets.json"}
```

**`hc_vault`** — reads from HashiCorp Vault KV. Tenant secrets are stored under a configurable path.

```json
TENANCY_SECRETS_CONNECTION={"type": "hc_vault", "url": "https://vault.internal", "token": "...", "vault_kv_path": "secret/tenants"}
```

### How to Add a New Secrets Provider

1. Implement a new `TenancySecretsProvider` in `config/tenancy_providers.py`. The interface requires `get_secrets(tenant_id)` returning a `TenantSecrets` instance.

2. Add a connection model in `config/settings.py`:

```python
class TenancySecretsBarConnection(BaseModel):
    type: Literal["bar"]
    # your connection fields
```

Include it in the `TenancySecretsConnection` union.

3. Register it in `config/tenancy_providers_factory.py`:

```python
if connection.type == "bar":
    return BarSecretsProvider(connection)
```

4. Set `TENANCY_SECRETS_CONNECTION` in `.env` with `"type": "bar"` and your connection fields.

---

## Identity & User Data

User identity is resolved independently of auth. Set `USER_DATA_SOURCE` to one of:

- `header` — reads `X-User-ID` and optional `X-User-Email`, `X-User-Roles`
- `jwt` — decodes `Authorization: Bearer <token>` (does not validate — validation is the gateway's job)
- `claims` — reads `X-User-Claims` as a JSON header

---

## Auth

fastkit(ty) is intentionally auth-agnostic. Auth is a peer concern — it belongs upstream, not inside a multi-tenant service template.

The recommended pattern:

```
Client → API Gateway / BFF → Auth Service (Keycloak, Auth0, ...)
                ↓ validated token
         fastkit(ty) service
```

A gateway validates tokens before requests reach your FastAPI service. Offline JWT validation for the common case, a blocking server-side check only when you genuinely need it (forced logout, token revocation, high-stakes ops). By the time a request hits your service, auth is already done.

**Why keep auth separate?**

- Multi-tenant auth is its own problem — tenant resolution, per-tenant token claims, and permission scoping belong in the auth layer, not scattered across service dependencies
- Vendor abstraction — your service never imports an Auth0 SDK or Keycloak client; it reads claims from a validated token
- Evolve independently — add MFA, rotate token strategies, or swap providers without touching business logic
- No distributed bottleneck — auth on issuance, not on every request; your service stays stateless and fast

Keep tokens lean. Fat tokens with many claims go stale fast and push you toward online validation on every request. Pass just enough to route and scope; let services hydrate what they need from their own context.

---

## Feature Configuration

Each tenant can define feature-specific config under `features`. Feature values are arbitrary JSON — the shape is yours to define per feature key.

```json
{
  "tenant_1": {
    "tenant_id": "tenant_1",
    "display_name": "Tenant One",
    "is_active": true,
    "features": {
      "greet": { "message": "Hello, welcome '{tenant_name}'!" }
    }
  }
}
```

Resolving feature config in a route:

```python
@router.get("/hello", name="greet")
async def hello(
    tenant_config: TenantConfig = Depends(get_tenant_config),
    feature_config: FeatureConfig | None = Depends(get_feature_config("greet")),
):
    message = feature_config.get("message") if feature_config else None
    ...
```

`get_feature_config("greet")` returns `None` if the tenant has no config for that feature key — always handle the missing case with a sensible default.

Treat feature keys as a contract. Document the supported keys and their expected shape in code so the config and the route stay in sync.

---

## Tests

The project includes automated tests for the main behavior seams in the template:

- tenancy schema normalization
- user data parsing from headers, JWT payloads, and claims headers
- database dependency wiring
- service-layer behavior
- provider factories and provider adapters
- route-level behavior for `/v1/hello` and `/v1/blog-posts`
- database strategy isolation, eviction, tenant scoping, and dependency wiring

You do not need to start the FastAPI server before running tests. The suite uses FastAPI's in-process test client and shared pytest fixtures from `tests/conftest.py`.

```bash
# run the full suite
uv run pytest tests

# run a single file
uv run pytest tests/test_api_routes.py

# run by name
uv run pytest tests -k hello

# verbose output
uv run pytest tests -v
```

---

## Extending the Template

To add a new resource:

1. Add a model in `models/` — inherit from `TenantScopedModel`, `TimestampedModel`, or both
2. Add request/response schemas in `schemas/`
3. Add a service in `services/`
4. Add routes in `api/routes/v1/`
5. Wire dependencies from `api/deps/`

Keep routes thin. If a route handler is doing more than resolving dependencies, calling a service method, and returning a response, the logic belongs in the service.

---

## Roadmap

- Alembic migrations and provisioning workflows — including automatic `updated_at` trigger wiring per `TimestampedModel` table
- Dockerfile / docker-compose
- Structured logging
- Logfire Pydantic logging
- Extract the DB strategy layer as a standalone SQLAlchemy extension (`sqlalchemy-tenancy` or similar) — the layer is already designed for this: configure a strategy and DB secrets, get sessions, everything else is invisible