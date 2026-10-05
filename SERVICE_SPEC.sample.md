# Sample Service Specification (Reference Example)

> This is a reference example showing how `SERVICE_SPEC.md` looks once a service is fully configured.
> Use this as a guide, or let Kitty (`AGENTS.md`) guide you through scaffolding your own service in `SERVICE_SPEC.md`.

## Status
`status: active`

---

## 1. Service Identity
- **Service Name**: `blog-platform-service`
- **Domain**: Multi-Tenant Blogging Platform
- **Description**: Allows tech companies to publish articles with per-tenant daily posting quotas and custom greetings.

---

## 2. Multi-Tenancy Strategy
- **Active Strategy**: `row`
- **Isolation Rationale**: Shared PostgreSQL database with `tenant_id` column-level scoping via `TenantScopedModel`.

---

## 3. Configuration & Secrets Providers
- **Config Provider**: `json`
  - File: `tenants_config.json`
- **Secrets Provider**: `json`
  - File: `tenants_secrets.json`
- **Identity Ingestion**: `gateway_headers` (`X-User-ID`, `X-User-Roles`)

---

## 4. Domain Models & Resources

### BlogPost
- **Table**: `blog_posts`
- **Base Class**: `TenantScopedModel`, `TimestampedModel`, `Base`
- **Fields**:
  - `id`: Integer (Primary Key)
  - `title`: String(255)
  - `content`: Text
  - `author`: String(255) (User ID)
  - `tenant_id`: String(64) (Inherited from `TenantScopedModel`)
  - `created_at`: DateTime(UTC) (Inherited from `TimestampedModel`)
  - `updated_at`: DateTime(UTC) (Inherited from `TimestampedModel`)

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
