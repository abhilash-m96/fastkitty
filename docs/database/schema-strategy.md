# Schema Strategy (PostgreSQL Schemas)

The **`schema` strategy** isolates tenants using native PostgreSQL schema namespaces within a single shared database instance.

```env
TENANCY_DB_STRATEGY=schema
```

---

## Secret Configuration Shape

All tenants share a single `database_uri`, but each tenant provides a distinct `schema_name`:

```json
{
  "airbnb": {
    "tenant_id": "airbnb",
    "database_config": {
      "database_uri": "postgresql+asyncpg://shared_user:password@localhost:5432/fastkitty_shared",
      "host": "localhost",
      "port": 5432,
      "username": "shared_user",
      "password": "password",
      "database_name": "fastkitty_shared",
      "schema_name": "airbnb"
    }
  }
}
```

---

## How It Works Under the Hood

### Dynamic `search_path` Management
1. When a request for tenant `airbnb` arrives, FastKitty acquires a session from the shared engine pool.
2. FastKitty attaches an `after_begin` event listener to the session:
   ```sql
   SET LOCAL search_path TO "airbnb";
   ```
   > [!IMPORTANT]
   > **Public Schema Fallback Dropped**: FastKitty deliberately excludes `public` from runtime `SET LOCAL search_path`. If `public` were in the search path, a tenant whose schema exists but has not yet been migrated could fall back to reading or writing shared tables in the public schema. Isolating the search path strictly to the tenant schema ensures that unmigrated tables fail fast rather than leaking data across tenants.
3. Because `SET LOCAL` is transaction-scoped, it automatically applies at the start of every transaction, remains active across commits, re-applies automatically if the transaction is rolled back (e.g., on caught errors or retries), and cleanly reverts upon transaction end when the connection is returned to the pool without risking connection pool contamination.
4. All table references (`SELECT * FROM blog_posts`) automatically resolve to `airbnb.blog_posts`.

### Security & Safety Protections
* **SQL Injection Guard**: Schema names are validated as safe SQL identifiers using regex (`^[a-zA-Z_][a-zA-Z0-9_]*$`) before being formatted into `SET LOCAL search_path`.
* **Reserved Schema Protection**: Reserved PostgreSQL schemas (`public`, `pg_catalog`, `information_schema`) are strictly rejected.
* **Transaction-Scoped Isolation**: Using `SET LOCAL` attached to the `after_begin` event hook guarantees that even if a tenant session encounters an error or explicit `rollback()`, search path settings do not leak across pooled connections to subsequent requests.
