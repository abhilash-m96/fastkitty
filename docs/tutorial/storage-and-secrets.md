# 2. Tenant Secrets & Database Strategies

In the previous step, we saw how the `BlogPostsService` created and queried blog posts while enforcing daily quotas.

Now let's look at **how tenant secrets and database connections are wired**, and how FastKitty enforces data isolation across tenants.

---

## ⚠️ The Universal Rule: Database Secrets are Required for ALL Strategies

A common misconception in multi-tenancy is thinking: *"If all tenants share one database in the `row` strategy, I don't need database secrets for each tenant."*

In FastKitty, **every discoverable tenant MUST have its database connection configuration defined in secrets — even when sharing the exact same database.**

```json
// tenants_secrets.json
{
  "spotify": {
    "tenant_id": "spotify",
    "database_config": {
      "database_uri": "postgresql+asyncpg://shared_user:pass@localhost:5432/fastkitty_shared",
      "host": "localhost",
      "port": 5432,
      "username": "shared_user",
      "password": "pass",
      "database_name": "fastkitty_shared"
    }
  },
  "airbnb": {
    "tenant_id": "airbnb",
    "database_config": {
      "database_uri": "postgresql+asyncpg://shared_user:pass@localhost:5432/fastkitty_shared",
      "host": "localhost",
      "port": 5432,
      "username": "shared_user",
      "password": "pass",
      "database_name": "fastkitty_shared"
    }
  }
}
```

### Why FastKitty requires this:
1. **Fail-Fast Startup Validation**: At application boot, FastKitty reads the active `TENANCY_DB_STRATEGY` and cross-validates every registered tenant's secrets. If any tenant is missing connection parameters, the server refuses to start — preventing runtime 500 errors on production traffic.
2. **Seamless Strategy Upgrades**: Because every tenant already has its own secrets record, upgrading a tenant from a shared database to a dedicated database cluster requires updating only their secret entry, without altering code or schema configurations.

> [!TIP]
> **Connecting to Cloud Databases (AWS RDS, Supabase, Neon) with SSL**:
> You do not need to assemble a long URI manually. Specify discrete fields and set `"ssl": "require"` (or `true`) directly:
> ```json
> {
>   "netflix": {
>     "tenant_id": "netflix",
>     "database_config": {
>       "host": "netflix-db.cluster-xyz.us-east-1.rds.amazonaws.com",
>       "port": 5432,
>       "username": "netflix_admin",
>       "password": "secret_password",
>       "database_name": "netflix_db",
>       "ssl": "require"
>     }
>   }
> }
> ```
> FastKitty will automatically compose the `postgresql+asyncpg` URI with `?ssl=require`.

---

## Which Strategy is Running for the Blog Posts Example?

FastKitty supports three database isolation strategies, controlled by a single environment variable:

```bash
TENANCY_DB_STRATEGY=database  # Options: database | schema | row
```

In the out-of-the-box local setup and Docker stack:
* FastKitty defaults to **`TENANCY_DB_STRATEGY=database`**, where each tenant connects to its own isolated database instance (`tenant_1` and `tenant_2` pre-created by `docker/init-db.sh`).
* FastKitty manages connections using an **LRU connection pool**, ensuring that having hundreds of tenants does not exhaust server memory or PostgreSQL connection limits.

---

## How Each Strategy Operates on Disk

```mermaid
flowchart LR
    subgraph Row ["Row Strategy (Shared Table)"]
        direction TB
        R_App["FastKitty API"] --> R_DB[("Shared DB (fastkitty_shared)")]
        R_DB --- R_T["Table: blog_posts
        WHERE tenant_id = 'spotify'"]
    end

    subgraph Schema ["Schema Strategy (PostgreSQL Schemas)"]
        direction TB
        S_App["FastKitty API"] --> S_DB[("Shared DB (fastkitty_shared)")]
        S_DB --- S_T1["airbnb.blog_posts"]
        S_DB --- S_T2["stripe.blog_posts"]
    end

    subgraph DB ["Database Strategy (Dedicated DBs)"]
        direction TB
        D_App["FastKitty API"] --> D_DB1[("Dedicated DB: netflix_prod")]
        D_App --> D_DB2[("Dedicated DB: uber_prod")]
    end
```

### 1. `row` Strategy (Shared Table)
- **Secret Requirement**: Shared DB URI for all tenants.
- **Mechanism**: FastKitty automatically stamps `post.tenant_id = 'spotify'` during write and injects `WHERE tenant_id = 'spotify'` on queries.
- **Best For**: Starter tiers, low infra cost.

### 2. `schema` Strategy (PostgreSQL Schemas)
- **Secret Requirement**: Shared DB URI + `"schema_name": "airbnb"` in each tenant's secret.
- **Mechanism**: FastKitty automatically executes transaction-scoped `SET LOCAL search_path TO "airbnb"` on transaction start via an `after_begin` hook, ensuring isolation survives rollbacks, prevents pooled connection leakage, and avoids leaking unmigrated fallback data from `public`.
- **Best For**: Mid-tier isolation without provisioning new database instances.

### 3. `database` Strategy (Dedicated Databases)
- **Secret Requirement**: Unique `database_uri` pointing to an isolated database for each tenant.
- **Mechanism**: Dedicated async engine pooled via an internal LRU cache.
- **Best For**: Enterprise tenants with compliance, SOC2, or high throughput demands.

---

## 📚 Deep-Dive Documentation

Want to dive deeper into the database layer? Explore our dedicated database guides:

* 📖 **[The 3 Strategies & Tradeoffs Comparison](../database/overview-and-tradeoffs.md)**: Isolation, operational complexity, and cost breakdown.
* 📖 **[Database Strategy & LRU Connection Pools](../database/database-strategy.md)**: How FastKitty manages engines safely across tenants.
* 📖 **[Schema Strategy & PostgreSQL search_path](../database/schema-strategy.md)**: Connection lifecycle, schema switching, and search path safety.
* 📖 **[Row Strategy & ORM Query Filtering](../database/row-strategy.md)**: Automatic query scoping and tenant model mixins.
* 📖 **[Database Migrations with Alembic](../database/migrations.md)**: Running multi-tenant migrations across databases and schemas.

---

## Next Step

Want to learn how to debug multi-tenant requests using Docker and Python's interactive debugger?  
👉 **[3. Docker & Interactive Debugging (pdb)](docker-and-debugging.md)**
