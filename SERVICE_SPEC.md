# Service Specification

> This specification is the persistent source of truth for your FastKitty service.
> When an AI assistant (Antigravity, Cursor, Claude Code, Copilot) runs in this repository,
> it consults this file to understand the architecture, domain models, and active tenancy strategies.

## Status
`status: unconfigured`  <!-- Change to 'active' once your initial service is configured -->

---

## 1. Service Identity
- **Service Name**: `fastkitty-service`
- **Domain**: Multi-Tenant SaaS Backend
- **Description**: Add a 1-2 sentence description of what this service does.

---

## 2. Multi-Tenancy Strategy
- **Active Strategy**: `row`  <!-- Options: row (default), schema, database -->
- **Isolation Rationale**: Shared PostgreSQL database with `tenant_id` column-level scoping via `TenantScopedModel`.

---

## 3. Configuration & Secrets Providers
- **Config Provider**: `json`  <!-- Options: json (local dev), vault, ssm, consul -->
  - File: `tenants_config.json`
- **Secrets Provider**: `json`  <!-- Options: json (local dev), vault, ssm, consul -->
  - File: `tenants_secrets.json`
- **Identity Ingestion**: `gateway_headers`  <!-- Options: gateway_headers (X-User-Id, X-User-Roles), jwt -->

---

## 4. Domain Models & Resources

### BlogPost (Template Example)
- **Table**: `blog_posts`
- **Base Class**: `TenantScopedModel`, `TimestampedModel`
- **Fields**:
  - `id`: Integer (Primary Key)
  - `title`: String(255)
  - `content`: Text
  - `author`: String(255) (User ID)
  - `tenant_id`: String(64) (Inherited from `TenantScopedModel`)
  - `created_at`: DateTime (Inherited from `TimestampedModel`)
  - `updated_at`: DateTime (Inherited from `TimestampedModel`)

---

## 5. Endpoints & Route Contracts

| Method | Path | Route Name | Description | Tenant Feature Flag / Quota |
|---|---|---|---|---|
| `GET` | `/v1/hello` | `greet` | Tenant greeting | `greet.message` |
| `POST` | `/v1/blog-posts` | `blog_posts` | Create user blog post | `blog_posts.max_daily_posts` (Rate Limit) |
| `GET` | `/v1/blog-posts` | `blog_posts_list` | List user blog posts | — |
| `GET` | `/v1/blog-posts/{id}`| `blog_posts_get` | Get blog post by ID | — |
| `PUT` | `/v1/blog-posts/{id}`| `blog_posts_update`| Update blog post | — |
| `DELETE`| `/v1/blog-posts/{id}`| `blog_posts_delete`| Delete blog post | — |

---

## 6. Tenant-Specific Behavior (`tenants_config.json`)

```json
{
  "tenant_1": {
    "display_name": "Tenant One",
    "is_active": true,
    "features": {
      "greet": {
        "message": "Hello {tenant_name}!"
      },
      "blog_posts": {
        "max_daily_posts": 1
      }
    }
  },
  "tenant_2": {
    "display_name": "Tenant Two",
    "is_active": true,
    "features": {
      "greet": {
        "message": "Welcome back {tenant_name}!"
      },
      "blog_posts": {
        "max_daily_posts": 5
      }
    }
  }
}
```
