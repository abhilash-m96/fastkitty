# fastkit(ty) 😼  

![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.142+-009688)
![License](https://img.shields.io/github/license/abhilash-m96/fastkitty?v=2)
![Stars](https://img.shields.io/github/stars/abhilash-m96/fastkitty?style=social&v=2)

---

## **Ever needed your FastAPI service to behave differently for different tenants?**
- Give one tenant unlimited API access while restricting another?
- Enable a feature for one tenant but disable it for another?
- Make your application behave differently based on which tenant is making the request?

---

That's multi-tenant SaaS — and **fastkit(ty) 😼** is a FastAPI multi-tenant service toolkit and template built for it.

A pragmatic foundation for building multi-tenant services with explicit tenant context, clear dependency boundaries, and a service-first architecture.

Tenant awareness flows through your application — not hidden in globals or middleware — so your business logic stays predictable, testable, and easy to evolve.

Tenancy, feature flags, database strategy, config, secrets, and identity are all pluggable and cleanly separated, letting you adapt your model without rewriting your core business logic.

---

## **Why FastKit(ty)?**

* **You focus on business logic** — Tenancy, configuration, secrets, identity, and database wiring are handled for you. Configure what you need and focus on what matters.
* **Flexible by design** — Swap configuration or secrets providers, or plug in your own, without touching your core business logic.
* **Explicit over magic** — Tenant context flows through dependencies you can read, trace, and test. Nothing hidden.
* **Service-first architecture** — A clean service layer that can be exposed through HTTP, a CLI, or other interfaces.
* **Support multiple tenancy strategies** — Choose shared database, schema-per-tenant, or database-per-tenant with a single flag.

---

## **What you get**

* Explicit tenancy via `X-Tenant-ID`
* Complete multi-tenant database setup with three isolation strategies to choose from: `database`, `schema`, and `row`
* Clean dependency injection for tenancy, database, and identity
* Service layer pattern with thin HTTP routes
* Configurable identity providers: headers or JWT
* Per-tenant feature configuration
* Extensible configuration and secrets providers
* Example CRUD service and HTTP routes
* Structured distributed tracing and telemetry with Pydantic Logfire
* Embedded AI Service Architect ([`AGENTS.md`](AGENTS.md)) and living specification ([`SERVICE_SPEC.md`](SERVICE_SPEC.md))

---

## 🤖 **Build with Your AI Coding Assistant**

FastKitty is designed to be **agent-native**. It ships with an embedded Service Architect protocol in [`AGENTS.md`](AGENTS.md) and state persistence in [`SERVICE_SPEC.md`](SERVICE_SPEC.md).

> [!TIP]
> **The Recommended Developer Experience:**  
> Rather than manually writing boilerplate, clone the repo, open it in your AI coding assistant (**Cursor**, **Antigravity**, **Claude Code**, **GitHub Copilot**, or **Windsurf**), and prompt:  
>  
> *"I want to build a [your-service-name]. Guide me through setup."*  
>  
> The **FastKitty Service Architect** will greet you, walk you through the architectural decisions one question at a time (tenancy strategy, config/secrets, domain entities, and API endpoints), recommend best practices grounded in these docs, and scaffold models, services, thin routes, and 100% passing tests for you.

---

## **Design Philosophy**

FastKitty is built on one single strong opinion: that **it should not be opinionated or impose its own opinions on how your application should be built.**
This isn't another framework with its own way of doing things *(IYKYK).* Instead, it follows a set of fundamental software design principles, and if you're comfortable with them, FastKitty should feel pretty natural.

> Bored? 👉 **[Jump straight to Quickstart](docs/quickstart/quickstart.md)**.  
> Nerds, continue reading below.


- **Tenancy is infrastructure, not business logic**: Routes and services never know which DB strategy is active. They receive a session, query it, and return results. Whether that session points to a dedicated database, a schema-scoped connection, or a row-filtered shared pool is decided at startup and invisible above the dependency layer. This means your business logic doesn't change when you change your tenancy model.

- **Tenant context is explicit, not ambient**: Tenant identity flows through FastAPI's dependency injection — you can see it, trace it, and test it. There are no thread-locals, no request-scoped globals, no middleware that silently injects context. If a route needs tenant context, it declares it. If it doesn't, it doesn't.

- **Fail fast at startup**: Misconfiguration surfaces before traffic hits. During boot, `validate_tenancy_strategy_startup` cross-validates the active tenancy strategy across all discoverable tenants:
  - Every tenant defined in tenancy configuration must have a matching entry in tenancy secrets.
  - In `database` strategy, each tenant must resolve to a unique physical database identified by `(host, port, database_name)` (case-insensitive host comparison). Pointing two tenants at the same database—even with different usernames or passwords—raises immediately. Note: hostname aliases (e.g., `localhost` vs `127.0.0.1`) are evaluated as distinct strings and not resolved via DNS/IP.
  - In `row` and `schema` strategies, all tenants must share an identical `database_uri` and matching pool settings (`pool_size`, `max_overflow`, `pool_recycle`, `pool_pre_ping`).
  - In `schema` strategy, each tenant must define a valid `schema_name` (validated at boot against SQL injection patterns and reserved names like `public`), and schema names must be unique (validated case-insensitively and after PostgreSQL's 63-byte identifier truncation).
  - Any mismatch raises immediately at startup with masked connection URIs (passwords never leak) — not on the first request from a tenant.

- **Auth is a peer concern & Production Guards**: FastKitty is intentionally auth-agnostic. Auth belongs upstream — in an API Gateway or BFF — not inside microservices. FastKitty ingests already-validated identity via `USER_DATA_SOURCE`. In non-dev environments (`ENV != 'dev'`), FastKitty strictly enforces `TRUST_UPSTREAM_AUTH=true` at startup to ensure public identity headers cannot be spoofed. In JWT/Claims mode, `REQUIRE_TENANT_CLAIM=true` enforces that tokens cannot be replayed across tenants.

- **Config and secrets are provider-agnostic**: The template ships with file-based providers for local development and HashiCorp Vault/Consul adapters for production. Swapping providers requires no changes to business logic — only config.

- **Services own business logic**: HTTP routes are thin. They resolve dependencies, call a service method, and return a response. Business logic lives in services/ where it can be tested without an HTTP client and reused across interfaces.

- **Config-driven tenant variability (Zero hardcoded tenant checks)**: Business logic must never contain hardcoded branching on specific `tenant_id`s (e.g., `if tenant_id == "tenant_1": ...`). All behavioral divergence between tenants is modeled declaratively through feature flags, quotas, and capability settings in `tenants_config.json`, injected via `feature_config`, and consumed generically in the service class.

---

## 🗺️ **Roadmap: From Template to Interactive Generator**

FastKitty is actively evolving from a starter template into an interactive, **cookiecutter-like project generator & CLI toolkit** (`fastkitty init` / Cookiecutter):

* **Interactive Setup Wizard**: Capture business domain requirements, tenancy strategy (`row`, `schema`, `database`), upstream auth mode, and tier quotas interactively.
* **Zero-Bloat Scaffolding**: Generate clean, domain-specific models, pure services, thin routes, and 100% passing tests tailored directly to your service — eliminating the need to clean up sample blog-post boilerplate.
* **Production Cloud Adapters & Lifecycle Hooks**: Native adapters for Vault, AWS Secrets Manager, DynamoDB, plus automated runtime tenant schema and database provisioning.
* **Standalone SQLAlchemy Multi-Tenancy Package**: Extract the database engine into an independent PyPI package (`sqlalchemy-tenancy`) usable with vanilla SQLAlchemy, Flask, Django, or Celery.

👉 Read the full vision and milestones in the **[Product Roadmap](docs/roadmap.md)**.


---

## **Next Steps**

Ready to get started?  
Proceed to **[Quickstart: Setup & Run](docs/quickstart/quickstart.md)** to run the project locally or in Docker in under 60 seconds!