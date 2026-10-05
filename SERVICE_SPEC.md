# Service Specification

> This specification is the persistent source of truth for your FastKitty service.
> When an AI assistant (Antigravity, Cursor, Claude Code, Copilot) runs in this repository,
> it consults this file to understand the architecture, domain models, and active tenancy strategies.
>
> 💡 *See [`SERVICE_SPEC.sample.md`](SERVICE_SPEC.sample.md) for a completed reference example.*

## Status
`status: unconfigured`  <!-- Change to 'active' once your initial service is configured -->

---

## 1. Service Identity
- **Service Name**: `<!-- e.g. billing-service, document-vault, job-posting-service -->`
- **Domain**: `<!-- e.g. B2B Invoicing & Subscription Management -->`
- **Description**: `<!-- 1-2 sentence description of what this service does and its core purpose -->`

---

## 2. Multi-Tenancy Strategy
- **Active Strategy**: `row`  <!-- Options: row (default), schema, database -->
- **Isolation Rationale**: `<!-- e.g. Shared PostgreSQL database with tenant_id column scoping -->`

---

## 3. Configuration & Secrets Providers
- **Config Provider**: `json`  <!-- Options: json (local file), vault, consul -->
  - File / Connection: `tenants_config.json`
- **Secrets Provider**: `json`  <!-- Options: json (local file), vault, aws_secrets, gcp_secrets -->
  - File / Connection: `tenants_secrets.json`
- **Identity Ingestion**: `gateway_headers`  <!-- Options: gateway_headers (X-User-ID, X-User-Roles), jwt -->

---

## 4. Domain Models & Resources

<!-- Define your service entities here. Each tenant-scoped model should inherit TenantScopedModel and TimestampedModel. -->

<!-- Example template:
### ResourceName
- **Table**: `resource_table_name`
- **Base Class**: `TenantScopedModel`, `TimestampedModel`, `Base`
- **Fields**:
  - `id`: Integer (Primary Key)
  - `name`: String(255)
  - `tenant_id`: String(64) (Inherited from TenantScopedModel)
  - `created_at`: DateTime(UTC) (Inherited from TimestampedModel)
  - `updated_at`: DateTime(UTC) (Inherited from TimestampedModel)
-->

---

## 5. Endpoints & Route Contracts

<!-- List the REST endpoints your service exposes. -->

| Method | Path | Route Name | Description | Tenant Feature Flag / Quota |
|---|---|---|---|---|
| `GET` | `/v1/health` | `health_check` | Service health status | — |

---

## 6. Tenant-Specific Behavior (`tenants_config.json`)

<!-- Define how features, quotas, or rate-limits vary across tenant tiers. -->

```json
{
  "tenant_1": {
    "display_name": "Tenant One",
    "is_active": true,
    "features": {}
  },
  "tenant_2": {
    "display_name": "Tenant Two",
    "is_active": true,
    "features": {}
  }
}
```
