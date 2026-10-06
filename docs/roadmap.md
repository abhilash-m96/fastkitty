# FastKitty Product Roadmap 🗺️

FastKitty's mission is to provide Python developers with the ultimate foundation for building production-ready, multi-tenant SaaS services.

---

## 🎯 The Vision: From Static Starter to Interactive Generator

Today, FastKitty ships as a cloneable repository template. While this gives developers a working reference implementation (the `BlogPost` CRUD sample service), it also means:
- Developers must manually delete or overwrite the blog post models, schemas, and routes.
- Adapting the service to a new business domain requires manual boilerplate editing.

Our primary architectural evolution is transforming FastKitty into an **interactive, cookiecutter-like project generator & CLI toolkit** (`fastkitty init` / Cookiecutter / Copier).

Instead of cloning a pre-baked blog app, developers will be prompted with an interactive setup wizard that captures their exact requirements and generates a lean, production-ready service customized to their domain with **zero bloat**.

---

## 🚀 Roadmap Milestones

### Phase 1: Interactive Service Generator (Cookiecutter / CLI Wizard)
- [ ] **Interactive Requirements Collection**:
  - Prompt for service name, business domain (e.g., `invoicing-service`, `document-vault`, `job-board`), and core entities.
  - Neutral selection of multi-tenancy database strategy (`row`, `schema`, `database`).
  - Selection of upstream authentication mode (`header`, `jwt`, or `claims`).
  - Selection of configuration and secrets providers (local file-based JSON, HashiCorp Vault, AWS Secrets Manager, or Consul).
- [ ] **Declarative Tenant Variability Generator**:
  - Wizard to capture tenant-tier differentiators (quotas, feature toggles, capability flags).
  - Pre-generate `tenants_config.json` with domain-specific features.
- [ ] **Zero-Bloat Domain Scaffolding**:
  - Automatically scaffold clean SQLAlchemy models (`TenantScopedModel`, `TimestampedModel`), Pydantic schemas, pure service classes, and thin route handlers.
  - Eliminate the bundled `BlogPost` sample code in generated projects.
  - Auto-generate initial Alembic migration scripts and 100% passing test suites for the generated domain.

---

### Phase 2: First-Class Cloud & Secret Adapters
- [ ] **AWS Secrets Manager & SSM Parameter Store**: Native production adapters for AWS-native stacks.
- [ ] **Google Cloud Secret Manager**: Native adapter for GCP cloud environments.
- [ ] **Redis / DynamoDB Config Providers**: High-performance, distributed key-value backends for live tenant feature flag updates without restarts.
- [ ] **Tenancy Provider Caching & In-Memory TTL**: In-memory caching and TTL layer for remote config & secrets providers (Vault, Consul) to eliminate per-request network roundtrips.
- [ ] **Environment-Aware Hot-Reloading**: Dynamic cache invalidation when tenant quotas or feature flags change upstream.

---

### Phase 3: Tenant Lifecycle & Provisioning Hooks
- [ ] **Dynamic Tenant Onboarding API**:
  - Secure administrative endpoints to register new tenants at runtime.
  - Automatic database creation (in `database` mode) or schema namespace initialization with tables (in `schema` mode) upon tenant registration.
- [ ] **Tenant Migration Runner**:
  - Automated concurrent migration engine that rolls out Alembic schema migrations across hundreds of tenant databases/schemas safely with rollback support.
- [ ] **Tenant Offboarding & Data Deletion**:
  - Compliant GDPR / data-retention lifecycle hooks to cleanly drop tenant schemas or archive isolated tenant databases.

---

### Phase 4: Standalone SQLAlchemy Multi-Tenancy Package (`sqlalchemy-tenancy`)
- [ ] **Decouple Database Engine**:
  - Extract the database strategy layer (`db/tenancy_strategy.py`, `db/session.py`, `TenantScopedModel`) into an independent, standalone Python package published to PyPI (e.g. `sqlalchemy-tenancy` or `fastkitty-tenancy`).
  - Framework-agnostic: usable with vanilla SQLAlchemy, Flask, Django, Celery background workers, or standalone scripts without requiring FastAPI.
- [ ] **Modular Strategy Plugins**:
  - Zero-overhead imports where applications only load the driver/strategy dependencies they actively configure.

---

### Phase 5: Embedded Agentic Co-Pilot (Kitty 😼)
- [ ] **AI-Assisted Continuous Evolution**:
  - Deepen the embedded Service Architect protocol (`AGENTS.md`) to guide developers through adding new routes, mutating schemas, and generating zero-downtime migrations.
  - Automated test generation for every newly added tenant capability flag or quota limit.

---

## 💡 Community & Contributions

Have ideas or requests for FastKitty's future? We would love to collaborate:
- Open a feature proposal in [GitHub Issues](https://github.com/abhilash-m96/fastkitty/issues).
- Discuss architectural improvements in [GitHub Discussions](https://github.com/abhilash-m96/fastkitty/discussions).
