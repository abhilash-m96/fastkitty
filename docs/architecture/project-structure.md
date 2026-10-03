# Project Structure & Component Cleanliness

FastKitty is organized around a simple architectural goal: **clean separation of concerns with zero hidden magic**.

Every component has one responsibility, depends only on what it needs, and can be enhanced, extended, and unit-tested in complete isolation.

---

## 📁 Repository Layout

```text
fastkitty/
├── main.py                     # FastAPI application entrypoint & lifespan
├── api/
│   ├── routes/
│   │   └── v1/
│   │       ├── hello.py        # Dynamic greet endpoint
│   │       └── blog_posts.py   # Multi-tenant blog CRUD routes
│   └── deps/
│       ├── tenancy.py          # Tenant resolution & feature config dependencies
│       ├── db.py               # Database session & service injection
│       └── user_data.py        # User identity resolution (headers or JWT)
├── services/
│   └── blog_posts_service.py   # Pure business logic (transport & strategy-agnostic)
├── models/
│   ├── base.py                 # Declarative Base, TenantScopedModel, TimestampedModel
│   └── posts.py                # BlogPost entity
├── schemas/
│   ├── posts.py                # Pydantic request & response models
│   ├── tenancy.py              # TenantConfig, FeatureConfig, SecretConfig
│   └── user_data.py            # UserData identity schema
├── config/
│   ├── settings.py             # Application environment settings (Pydantic BaseSettings)
│   ├── tenancy_config.py       # Tenancy config provider interface & loader
│   ├── tenancy_secrets.py      # Tenancy secrets provider interface & loader
│   └── logfire_config.py       # Pydantic Logfire telemetry setup
├── db/
│   ├── engine.py               # Strategy-aware engine factory & LRU connection pools
│   └── session.py              # AsyncSession generator per tenant
├── alembic/                    # Multi-tenant migration scripts
│   └── env.py                  # Multi-database & multi-schema migration runner
├── tenants_config.json         # Local tenant feature flags & metadata
└── tenants_secrets.json        # Local tenant DB connection secrets
```

---

## Why Components are Clean & Lean

| Component | Responsibility | What it Knows | What it NEVER Knows |
|---|---|---|---|
| **Route Handler** (`api/routes/`) | HTTP deserialization, status codes, response shapes | Pydantic schemas, dependency signatures | SQL queries, rate limiting algorithms, DB strategy |
| **Dependency Layer** (`api/deps/`) | Resolving request context, auth, sessions | FastAPI `Request`, config providers, DB engine | Business rules, response formatting |
| **Service Layer** (`services/`) | Business workflows, domain rules, transactions | Domain models, `AsyncSession` | HTTP requests, cookies, headers, status codes, DB strategy |
| **Model Layer** (`models/`) | Database schema definition, column types, relationships | SQLAlchemy Declarative Base | How sessions are acquired or who the current tenant is |
| **Config & Secrets** (`config/`) | Loading credentials and feature flags from storage | JSON files, Vault, Consul, Redis | Routes, services, or business logic |

---

## How to Enhance & Extend Each Component

### 1. Extending the Service Layer
Services only take an `AsyncSession` in their `__init__`. To add business logic:
- Add a new method in `services/`.
- Use standard SQLAlchemy async queries.
- Because services are decoupled from HTTP, you can call them from background workers (Celery, ARQ), CLI scripts, or async queues with no changes.

### 2. Extending Dependencies
If you need new context (e.g. tenant billing status, user roles):
- Add a helper function in `api/deps/`.
- Use `Depends()` to compose dependencies naturally.

### 3. Swapping Infrastructure Providers
FastKitty uses interface protocols for config and secrets. To switch from local JSON files to HashiCorp Vault or AWS Secrets Manager:
- Subclass the provider base class in `config/`.
- Update `TENANCY_SECRETS_PROVIDER` in your `.env`.
- Not a single line of application code or route code changes.

---

## Testing Made Effortless

Because components have explicit seams, testing is fast and deterministic:

### 1. Unit Testing Services (Zero HTTP, Zero Network)
Test your business logic by passing an in-memory SQLite session directly to the service:

```python
async def test_create_post_enforces_quota(async_session):
    service = BlogPostsService(async_session)
    # Test business logic directly
    post = await service.create_post(..., feature_config={"max_daily_posts": 1})
    ...
```

### 2. Integration Testing API Routes
Override FastAPI dependencies using `app.dependency_overrides` without needing real cloud services:

```python
app.dependency_overrides[get_tenant_config] = lambda: mock_tenant_config
app.dependency_overrides[get_db_session] = lambda: test_session
```

---

## Next Step

Want to see how all these components come together from scratch? Follow our end-to-end guide:

👉 **[How to Add a New Route & Table: Complete End-to-End Walkthrough](../guides/adding-a-new-route.md)**
