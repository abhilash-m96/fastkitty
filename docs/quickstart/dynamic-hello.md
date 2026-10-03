# The Greet Endpoint (Dynamic Hello)

The fastest way to understand FastKitty is to send two requests to the exact same URL, with only the `X-Tenant-ID` header changed.

---

## 1. Send Request for Tenant 1

```bash
curl -X 'GET' \
  'http://127.0.0.1:8000/v1/hello' \
  -H 'accept: application/json' \
  -H 'X-Tenant-ID: tenant_1'
```

**Response:**
```json
{
  "message": "Hello, welcome 'Tenant One'!"
}
```

---

## 2. Send Request for Tenant 2

Now change the header to `tenant_2`:

```bash
curl -X 'GET' \
  'http://127.0.0.1:8000/v1/hello' \
  -H 'accept: application/json' \
  -H 'X-Tenant-ID: tenant_2'
```

**Response:**
```json
{
  "message": "Hi 'Tenant Two', welcome!"
}
```

**Same endpoint. Same route handler. Completely different tenant-configured response.**

---

## 3. Here's the Config Driving It

In `tenants_config.json`, each tenant configures its own identity and feature values under `features`:

```json
{
  "tenant_1": {
    "tenant_id": "tenant_1",
    "display_name": "Tenant One",
    "is_active": true,
    "features": {
      "greet": {
        "message": "Hello, welcome '{tenant_name}'!"
      }
    }
  },
  "tenant_2": {
    "tenant_id": "tenant_2",
    "display_name": "Tenant Two",
    "is_active": true,
    "features": {
      "greet": {
        "message": "Hi '{tenant_name}', welcome!"
      }
    }
  }
}
```

---

## 4. And Here's the Clean Route Handler

Notice how clean and explicit the route handler in `api/routes/v1/hello.py` is:

```python
@router.get("/hello", name="greet")
async def hello(
    tenant_config: TenantConfig = Depends(get_tenant_config),
    feature_config: FeatureConfig | None = Depends(get_feature_config("greet")),
):
    message = feature_config.get("message") if feature_config else None
    tenant_name = tenant_config.display_name
    if not message:
        message = f"Hello {tenant_name}!"
    try:
        message = message.format(tenant_name=tenant_config.display_name)
    except (KeyError, ValueError):
        pass

    return {"message": message}
```

### What just happened?
1. FastKitty intercepted the incoming `X-Tenant-ID` header.
2. The `get_tenant_config` dependency fetched the tenant's record, verified the tenant was active, and injected `TenantConfig`.
3. The `get_feature_config("greet")` dependency cleanly extracted the tenant-specific feature payload.
4. If an invalid or inactive tenant was passed, FastKitty failed fast before running the route logic.

---

## Next Step

Ready to build a real-world multi-tenant feature with rate limits and quota enforcement?  
👉 **[Tutorial: Blog App (CRUD & Rate Limiting)](../tutorial/blog-posts.md)**
