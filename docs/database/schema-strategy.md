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
1. When a request for tenant `airbnb` arrives, FastKitty acquires a connection from the shared engine pool.
2. FastKitty executes:
   ```sql
   SET search_path TO "airbnb", public;
   ```
3. All table references (`SELECT * FROM blog_posts`) automatically resolve to `airbnb.blog_posts`.
4. When the session finishes (even if an unhandled exception occurred), FastKitty resets the connection before returning it to the pool:
   ```sql
   RESET search_path;
   ```

### Security & Safety Protections
* **SQL Injection Guard**: Schema names are validated as safe SQL identifiers using regex (`^[a-zA-Z_][a-zA-Z0-9_]*$`) before being formatted into `SET search_path`.
* **Reserved Schema Protection**: Reserved PostgreSQL schemas (`public`, `pg_catalog`, `information_schema`) are strictly rejected.
* **Fail-Safe Cleanup**: If `RESET search_path` itself raises a network error, FastKitty invalidates the underlying socket to prevent connection contamination.
