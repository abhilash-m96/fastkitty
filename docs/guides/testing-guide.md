# Testing Guide & Test Seams

FastKitty includes automated tests for all core behavior seams in the template.

You **do not need to start the FastAPI server** before running tests. The suite uses FastAPI's in-process test client and shared pytest fixtures from `tests/conftest.py`.

---

## Running the Test Suite

```bash
# Run the full test suite
uv run pytest tests

# Run a single test file
uv run pytest tests/test_telemetry.py

# Run tests by expression or name
uv run pytest tests -k logfire

# Run with verbose output and coverage
uv run pytest tests -v
```

---

## Key Test Seams

The automated test suite verifies:
1. **Tenancy Schema Normalization**: Ensures tenant IDs and secret configurations conform to strict schemas.
2. **User Data Parsing**: Validates identity extraction across `header`, `jwt`, and `claims` modes.
3. **Database Dependency Wiring**: Ensures async database sessions are correctly acquired and cleaned up per request.
4. **Service-Layer Behavior**: Confirms business logic and error handling in `services/`.
5. **Provider Factories & Adapters**: Tests `file`, `vault`, and `consul` config and secrets loaders.
6. **Route-Level Behavior**: Validates status codes, payload serialization, and headers on `/v1/hello` and `/v1/blog-posts`.
7. **Database Isolation Strategies**: Verifies engine LRU eviction (`database`), schema switching (`schema`), and ORM criteria injection (`row`).
8. **Telemetry & Logfire**: Validates multi-tenant span attributes and console fallbacks.

---

## Writing Tests with Dependency Overrides

FastKitty's use of FastAPI dependency injection makes writing mock tests effortless using `app.dependency_overrides`:

```python
import pytest
from httpx import AsyncClient
from main import app
from api.deps.tenancy import get_tenant_config
from schemas.tenancy import TenantConfig

@pytest.mark.asyncio
async def test_custom_tenant_behavior():
    mock_tenant = TenantConfig(
        tenant_id="test_corp",
        display_name="Test Corporation",
        is_active=True,
        features={"blog_posts": {"max_daily_posts": 10}},
    )
    app.dependency_overrides[get_tenant_config] = lambda: mock_tenant

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/v1/hello", headers={"X-Tenant-ID": "test_corp"})
        assert response.status_code == 200

    app.dependency_overrides.clear()
```
