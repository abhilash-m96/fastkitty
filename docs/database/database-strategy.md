# Database Strategy (Dedicated DB per Tenant)

The **`database` strategy** provides the strongest level of tenant isolation available. Every tenant connects to their own independent database instance, cloud cluster, or file.

```env
TENANCY_DB_STRATEGY=database
TENANCY_DATABASE_MAX_ENGINES=50
```

---

## Secret Configuration Shape

In `tenants_secrets.json`, each tenant defines its own complete database connection parameters:

```json
{
  "netflix": {
    "tenant_id": "netflix",
    "database_config": {
      "database_uri": "postgresql+asyncpg://netflix_admin:secret@netflix-cluster.rds.amazonaws.com:5432/netflix_db",
      "host": "netflix-cluster.rds.amazonaws.com",
      "port": 5432,
      "username": "netflix_admin",
      "password": "secret",
      "database_name": "netflix_db"
    }
  }
}
```

---

## How It Works Under the Hood

### Bounded LRU Engine Registry
In high-scale multi-tenant systems, creating a connection pool for every tenant can quickly exhaust database connections and application memory.

FastKitty solves this by maintaining a **Bounded LRU (Least Recently Used) Engine Registry**:
- Engine instances are cached keyed by their normalized database URI.
- The cache size is governed by `TENANCY_DATABASE_MAX_ENGINES` (default: 50).
- When active tenants exceed the limit, the least-recently used engine is evicted.
- **Graceful disposal**: Evicted engines wait for all in-flight sessions to complete before disposing connections — active queries are never severed.

### Startup Validation
At application boot, FastKitty:
1. Validates that every registered tenant has a valid, parseable async database URI.
2. Ensures all required credentials (`host`, `database_name`) are present.
3. Tests database connectivity if configured, failing fast before traffic hits.
