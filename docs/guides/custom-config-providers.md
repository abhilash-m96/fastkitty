# Custom Config Providers (Consul, Redis, AWS AppConfig)

In FastKitty, tenant feature flags and metadata are separated from database secrets.

Tenant configuration is managed via **Config Providers**, allowing you to change feature flags in real time (e.g. updating Spotify's `max_daily_posts` from 1 to 10) without restarting your FastAPI app or deploying new code.

---

## The Provider Interface

Every tenancy config provider implements `BaseTenancyConfigProvider` in `config/tenancy_config.py`:

```python
from abc import ABC, abstractmethod
from schemas.tenancy import TenantConfig

class BaseTenancyConfigProvider(ABC):
    @abstractmethod
    async def get_tenant_config(self, tenant_id: str) -> TenantConfig | None:
        """Fetch metadata, display name, and feature flags for a single tenant."""
        ...

    @abstractmethod
    async def get_all_tenant_configs(self) -> dict[str, TenantConfig]:
        """Fetch all tenant configurations for startup validation."""
        ...
```

---

## Built-In Providers

| Provider Name | Value in `.env` | Storage Location | Use Case |
|---|---|---|---|
| **File Provider** | `TENANCY_CONFIG_PROVIDER=file` | `tenants_config.json` | Local dev, static testing |
| **Consul Provider** | `TENANCY_CONFIG_PROVIDER=consul` | HashiCorp Consul KV | Distributed cloud configuration |

---

## Writing a Custom Provider (e.g., Redis)

To store and hot-reload tenant feature flags using Redis:

### 1. Implement the Provider
In `config/tenancy_config.py`:

```python
import json
import redis.asyncio as redis
from schemas.tenancy import TenantConfig
from config.tenancy_config import BaseTenancyConfigProvider

class RedisTenancyConfigProvider(BaseTenancyConfigProvider):
    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self.redis = redis.from_url(redis_url, decode_responses=True)

    async def get_tenant_config(self, tenant_id: str) -> TenantConfig | None:
        raw_data = await self.redis.get(f"fastkitty:tenant:{tenant_id}")
        if not raw_data:
            return None
        return TenantConfig.model_validate_json(raw_data)

    async def get_all_tenant_configs(self) -> dict[str, TenantConfig]:
        keys = await self.redis.keys("fastkitty:tenant:*")
        configs = {}
        for key in keys:
            tenant_id = key.split(":")[-1]
            raw_data = await self.redis.get(key)
            if raw_data:
                configs[tenant_id] = TenantConfig.model_validate_json(raw_data)
        return configs
```

### 2. Register & Configure
Register in `config/tenancy_config.py` and activate in `.env`:

```bash
TENANCY_CONFIG_PROVIDER=redis
REDIS_URL=redis://localhost:6379/0
```

Now, any changes made to a tenant's feature flags in Redis take effect immediately on subsequent requests!
