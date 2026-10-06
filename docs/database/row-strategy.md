# Row Strategy (Shared Table ORM Scoping)

The **`row` strategy** stores all tenants in a single shared database and shared tables in the `public` schema. Data isolation is enforced dynamically at the SQLAlchemy ORM layer.

```env
TENANCY_DB_STRATEGY=row
```

---

## Secret Configuration Shape

All tenants point to the same shared database. No `schema_name` is required, but credentials must still be present for every tenant:

```json
{
  "spotify": {
    "tenant_id": "spotify",
    "database_config": {
      "database_uri": "postgresql+asyncpg://shared_user:password@localhost:5432/fastkitty_shared",
      "host": "localhost",
      "port": 5432,
      "username": "shared_user",
      "password": "password",
      "database_name": "fastkitty_shared"
    }
  }
}
```

---

## How It Works Under the Hood

### 1. Automatic Query and Bulk Statement Filtering (`with_loader_criteria`)
When any ORM statement is executed (`select(BlogPost)`, bulk `update(BlogPost)`, or bulk `delete(BlogPost)`), FastKitty intercepts execution via `with_loader_criteria` and appends an automatic filter:
```sql
WHERE blog_posts.tenant_id = :current_tenant_id
```
Even if a developer forgets to add `.where(BlogPost.tenant_id == ...)` in a service query, bulk update, or bulk delete, the tenant filter is automatically guaranteed at the ORM layer.

### 2. Automatic Write Stamping
When a new model inheriting from `TenantScopedModel` is added to the session, FastKitty automatically sets:
```python
model.tenant_id = current_tenant_id
```

### 3. Cross-Tenant Mutation & Delete Guards
Before session flush (`before_flush`), FastKitty inspects all modified instances (including `session.new`, `session.dirty`, and `session.deleted`). If code attempts to mutate or delete a model instance whose `tenant_id` does not match the active request's tenant, FastKitty raises a `ValueError` before any SQL flush occurs.

### 4. ORM Bulk Insert Rejection
SQLAlchemy's ORM bulk insert construct (`insert(Model).values(...)`) bypasses the session identity map and `before_flush` lifecycle hooks. To prevent cross-tenant data corruption, FastKitty intercepts ORM insert execution and explicitly rejects bulk insert statements on `TenantScopedModel` classes:
```python
# Raises ValueError: Use session.add() for tenant-scoped models in row mode
await session.execute(
    insert(BlogPost).values(title="New Post", tenant_id="other_tenant")
)
```
Always persist models via `session.add(instance)`, ensuring tenant write-stamping and validation hooks run.

---

## Limitations & Defense-in-Depth

> [!WARNING]
> **Core Table Expressions & Raw SQL Bypass**:  
> FastKitty's automatic scoping is enforced at the SQLAlchemy ORM layer (`do_orm_execute` with `with_loader_criteria`).  
> - High-level ORM operations (`select(BlogPost)`, bulk `update(BlogPost)`, bulk `delete(BlogPost)`) are automatically scoped.
> - Low-level SQLAlchemy Core table expressions (`select(blog_posts_table)`) and raw SQL strings (`session.execute(text("SELECT * FROM blog_posts"))`) **bypass** ORM listeners.
> 
> For defense-in-depth in `row` tenancy mode, pair FastKitty with PostgreSQL **Row-Level Security (RLS)** policies scoped to a connection-level tenant session variable.
