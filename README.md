# fastkit(ty) 🐱

![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688)
![License](https://img.shields.io/github/license/abhilash-m96/fast-api-multi-tenant)
![Stars](https://img.shields.io/github/stars/abhilash-m96/fast-api-multi-tenant)

Ever needed to disable a feature for one customer but enable it for another?
Give one tenant unlimited API access and another a restricted workflow?
Make your service behave differently depending on which tenant is calling?

That’s multi-tenant SaaS — and fastkit(ty) 🐱 is a FastAPI template built for it.

A pragmatic foundation for building multi-tenant services with explicit tenant context, clear dependency boundaries, and a service-first architecture.

Tenant awareness flows through your application — not hidden in globals or middleware — so your business logic stays predictable, testable, and easy to evolve.

Tenancy, feature flags, database strategy, config, secrets, and identity are all pluggable and cleanly separated, letting you adapt your model without rewriting your core business logic.

---
## Why this template

* **Focus on business logic** — Tenancy, config, secrets, identity, and database wiring are handled for you. Configure what you need and build what matters.
* **Flexible by design** — Swap config or secrets providers, or plug in your own, without touching core business logic.
* **Explicit over magic** — Tenant context flows through dependencies you can read, trace, and test. Nothing hidden.
* **Service-first architecture** — A clean service layer that can be exposed via HTTP, CLI, or other interfaces.
* **Built to evolve** — Start with a shared database, then move to schema-per-tenant or database-per-tenant as your needs grow.

## What you get

* Explicit tenancy via `X-Tenant-ID`
* Different DB strategies for mult-tenancy
* Clean dependency injection (tenancy, DB, identity)
* Service layer pattern (thin HTTP routes)
* Configurable identity provider (headers or JWT)
* Per-tenant feature configuration
* Extensible config and secrets providers
* Example CRUD service and routes



**Quickstart (Local Dev with uv)**
1. Install dependencies:
```bash
   uv sync
```
2. Create your env file:
```bash
   cp .env.example .env
```
3. Run the API:
```bash
   uv run uvicorn main:app --reload
```
4. Open docs (dev only):
   - `http://localhost:8000/docs`

**Configuration**
The full list of settings is in `.env.example`. Key settings:
- `TENANCY_CONFIG_CONNECTION`: JSON config for tenancy config provider
- `TENANCY_SECRETS_CONNECTION`: JSON config for tenancy secrets provider
- `USER_DATA_SOURCE`: `header` | `jwt` | `claims`

**Tenancy Model**
Tenancy is resolved from the `X-Tenant-ID` header:
- `tenants_config.json` defines tenants, status, and per-tenant features
- `tenants_secrets.json` provides DB connection details

**Planned Roadmap**
- Configurable tenant ID resolution (custom header name, JWT claim, or custom resolver), similar to `USER_DATA_SOURCE`
- Shared DB with row-level tenancy (`tenant_id` column) and schema-per-tenant (single DB, separate schemas)
- Startup validation for config/secrets (behavior TBD: fail-fast vs warn; provider connectivity scope)

**Active Tenant Enforcement**
Tenant lookup and active checks are split into separate dependencies:
- `get_tenant_config` fetches tenant configuration (404 if missing)
- `require_active_tenant` enforces `is_active` (403 if inactive)
- Missing `X-Tenant-ID` returns 400

You can enforce active tenants at the parent router level:
```python
from fastapi import APIRouter, Depends
from api.deps.tenancy import require_active_tenant

router = APIRouter(
    tags=["Blog-Posts"],
    dependencies=[Depends(require_active_tenant)],
)
```

Or at the individual route level:
```python
from fastapi import APIRouter, Depends
from api.deps.tenancy import require_active_tenant

router = APIRouter(tags=["Greet"])

@router.get(
    "/hello",
    name="greet",
    dependencies=[Depends(require_active_tenant)],
)
async def hello():
    return {"message": "Hello!"}
```

**Tenancy Strategies**
- **Per-tenant DBs (implemented)**: each tenant has its own connection details in `tenants_secrets.json`
- **Schema-per-tenant (planned)**: one DB, separate schemas per tenant
- **Shared DB with tenant column (planned)**: single schema, enforced tenancy via `tenant_id`

**User Data Provider**
User identity is resolved independently of auth:
- `header` provider: `X-User-ID` and optional `X-User-Email`, `X-User-Roles`
- `jwt` provider: `Authorization: Bearer <token>`
- `claims` provider: `X-User-Claims` JSON header

**Auth**

fastkit(ty) is intentionally auth-agnostic. Auth is a peer concern — it belongs upstream, not inside a multi-tenant service template. This is a deliberate architectural choice, not a gap.

The recommended pattern:
```
Client → API Gateway / BFF → Auth Service (Keycloak, Auth0, ...)
                ↓ validated token
         fastkit(ty) service
```

A dedicated auth service handles token issuance, session management, and identity. A thin wrapper around it gives you vendor abstraction — swap providers without touching your gateway or service code. The gateway validates tokens before requests reach your FastAPI service: offline JWT validation for the common case, and a blocking server-side check only when you genuinely need it (forced logout, token revocation, high-stakes ops).

By the time a request hits your service, auth is already done.

**Why keep auth separate?**
- **Multi-tenant auth is its own problem** — tenant resolution, per-tenant token claims, and permission scoping belong in the auth layer, not scattered across service dependencies
- **Vendor abstraction** — your service never imports an Auth0 SDK or Keycloak client; it just reads claims from a validated token
- **Evolve independently** — add MFA, rotate token strategies, or swap providers without touching business logic
- **No distributed bottleneck** — auth on issuance, not on every request; your service stays stateless and fast

**What this template provides**

`USER_DATA_SOURCE` (`header` | `jwt` | `claims`) is how fastkit(ty) reads already-validated identity from incoming requests. It assumes auth has happened upstream. The `jwt` provider decodes the token — it does not validate or issue it. That's the gateway's job.

Keep tokens lean. Fat tokens with many claims go stale fast and push you toward online validation on every request. Pass just enough to route and scope; let services hydrate what they need from their own context.

**OpenAPI Docs**
In `dev` mode, interactive API docs are available at:
- `http://localhost:8000/docs`

**Project Layout**
- `api/routes`: HTTP routes
- `api/deps`: dependency wiring (tenancy, db, user data)
- `services`: business logic
- `models`: SQLAlchemy models
- `schemas`: Pydantic schemas
- `config`: config providers and settings
- `db`: database session / engine setup

**Feature Configuration (Per Tenant)**
Each tenant can define feature-specific config under `features`. Feature values are user-defined JSON.

Example in `tenants_config.json`:
```json
{
  "tenant_1": {
    "tenant_id": "tenant_1",
    "display_name": "Tenant One",
    "is_active": true,
    "features": {
      "greet": { "message": "Hello {display_name}!" }
    }
  }
}
```

Usage in a route:
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
        message = message.format(
            tenant_name=tenant_config.display_name,
        )
    except (KeyError, ValueError):
        pass

    return {"message": message}
```

**Provider Extensibility**
Config and secrets providers are pluggable. The default provider is file-based, but you can add new providers by:
1. Implementing a provider in `config/tenancy_providers.py`
2. Registering it in `config/tenancy_providers_factory.py`
3. Wiring a new connection type in `config/settings.py`

Currently supported providers:
- Config: `file` (default), `hc_consul`
- Secrets: `file` (default), `hc_vault`
- HashiCorp provider paths are configurable via connection JSON fields (`consul_prefix`, `vault_kv_path`).

**Adding a New Config Provider**
To add a new tenant config provider (e.g., DB, API, or a secrets manager):
1. Implement a new `TenancyConfigProvider` in `config/tenancy_providers.py`.
2. Add a connection model in `config/settings.py` (e.g., `TenancyConfigFooConnection`) and include it in `TenancyConfigConnection`.
3. Register it in `config/tenancy_providers_factory.py`.
4. Set `TENANCY_CONFIG_CONNECTION` in `.env` with the new provider type.

**Adding a New Secrets Provider**
To add a new tenant secrets provider:
1. Implement a new `TenancySecretsProvider` in `config/tenancy_providers.py`.
2. Add a connection model in `config/settings.py` (e.g., `TenancySecretsBarConnection`) and include it in `TenancySecretsConnection`.
3. Register it in `config/tenancy_providers_factory.py`.
4. Set `TENANCY_SECRETS_CONNECTION` in `.env` with the new provider type.

**Principles**
- HTTP concerns live in routes
- Business logic lives in services
- Dependencies are composable and testable
- Tenancy is explicit via headers
- User identity is pluggable
- Defaults favor clarity and extensibility

**Best Practices**
- Keep tenancy resolution in dependencies (`api/deps`) and avoid direct header access in routes
- Keep business logic in services; keep routes thin
- Treat `features` as a contract: document supported keys in code
- Use explicit route names for stable feature keys

**Extending the Template**
To add a new resource:
1. Add a model in `models/`
2. Add request/response schemas in `schemas/`
3. Add a service in `services/`
4. Add routes in `api/routes/v1/`
5. Wire dependencies from `api/deps/`

**Roadmap / Optional Enhancements**
- Alembic migrations
- Tests and CI
- Dockerfile / docker-compose
- Structured logging
