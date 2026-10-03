# Structured Logging & Telemetry with Pydantic Logfire

FastKitty comes with built-in, production-grade telemetry and distributed tracing powered by [Pydantic Logfire](https://pydantic.dev/logfire) and OpenTelemetry.

---

## What is Instrumented Automatically

* **FastAPI Endpoints**: Request paths, HTTP status codes, headers, response timings, and unhandled exceptions.
* **SQLAlchemy Queries**: Every SQL query executed across all tenant strategies (`database`, `schema`, `row`) is recorded with parameters and latency spans.
* **Pydantic Validation**: Model validation durations and schema validation errors.
* **Multi-Tenant Context Propagation**: Every active trace span is automatically tagged with:
  - `tenant.id` / `tenant_id`: The tenant handling the request (extracted from `X-Tenant-ID`).
  - `tenant.name`: Tenant display name (from tenant configuration).
  - `user.id` / `user.email` / `user.roles`: User identity attributes (from headers, JWT, or claims).

---

## Local Console Mode (Default — Zero Network, Free)

By default, Logfire sends **zero data over the network**:

```env
LOGFIRE_SEND_TO_LOGFIRE=false
```

When running FastKitty locally or in Docker, Logfire prints tree-structured, colored spans and query execution times directly to your terminal:

```text
17:01:57.495 GET /v1/hello [200 OK] (14.2ms)
  ├── extract_tenant_config (2.1ms) [tenant.id=tenant_1]
  └── select blog_posts where tenant_id = 'tenant_1' (3.8ms)
```

---

## Cloud Web Dashboard Mode (Optional — Free Tier Available)

If you or your team prefer a visual web dashboard with flame graphs, SQL query inspection, and live tenant filtering:

1. **Sign up for free** at [logfire.pydantic.dev](https://logfire.pydantic.dev) (The Personal plan includes **10 million records/month free** with 30-day retention).
2. Authenticate or retrieve your project write token:
   ```bash
   uv run logfire auth
   ```
   Or copy the project write token directly from the web dashboard.
3. Update your `.env` file:
   ```env
   LOGFIRE_SEND_TO_LOGFIRE=true
   LOGFIRE_TOKEN=your_logfire_token_here
   LOGFIRE_ENVIRONMENT=dev  # dev | staging | prod
   ```
4. Start your service:
   ```bash
   uv run uvicorn main:app --reload
   ```
   Open [logfire.pydantic.dev](https://logfire.pydantic.dev) to inspect incoming requests. You can filter traces instantly by tenant using SQL queries like:
   ```sql
   SELECT * FROM records WHERE attributes['tenant.id'] = 'tenant_1'
   ```

---

## Telemetry Configuration Reference

All settings can be configured via environment variables or `.env`:

| Variable | Type | Default | Description |
|---|---|---|---|
| `LOGFIRE_ENABLED` | `bool` | `true` | Master toggle to enable or disable Logfire telemetry. |
| `LOGFIRE_SEND_TO_LOGFIRE` | `bool` | `false` | When `false`, logs are emitted only to the terminal console (zero cloud traffic). Set to `true` to export to Logfire cloud. |
| `LOGFIRE_TOKEN` | `str \| null` | `null` | Your Logfire project write token (required if `LOGFIRE_SEND_TO_LOGFIRE=true`). |
| `LOGFIRE_ENVIRONMENT` | `str \| null` | `null` | Deployment environment tag (`dev`, `staging`, `prod`). Defaults to `ENV` setting. |
| `LOGFIRE_SERVICE_NAME` | `str \| null` | `null` | Service identifier for traces. Defaults to `APP_NAME` (`fastkitty`). |
| `LOGFIRE_CONSOLE` | `bool` | `true` | Enables colored, formatted output in the terminal console. |
