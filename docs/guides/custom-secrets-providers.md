# Custom Secrets Providers (HashiCorp Vault, AWS, GCP)

FastKitty decouples credential storage from your application code using a provider pattern.

Whether your tenant database credentials live in a local JSON file during development or in **HashiCorp Vault**, **AWS Secrets Manager**, or **GCP Secret Manager** in production, your application code remains completely unchanged.

---

## The Provider Interface

Every secrets provider inherits from `BaseTenancySecretsProvider` in `config/tenancy_secrets.py`:

```python
from abc import ABC, abstractmethod
from schemas.tenancy import TenantSecretConfig

class BaseTenancySecretsProvider(ABC):
    @abstractmethod
    async def get_tenant_secret(self, tenant_id: str) -> TenantSecretConfig | None:
        """Fetch database credentials and secrets for a single tenant."""
        ...

    @abstractmethod
    async def get_all_tenant_secrets(self) -> dict[str, TenantSecretConfig]:
        """Fetch all tenant secrets for fail-fast startup validation."""
        ...
```

---

## Built-In Providers

FastKitty ships with two production-ready providers:

| Provider Name | Value in `.env` | Storage Location | Use Case |
|---|---|---|---|
| **File Provider** | `TENANCY_SECRETS_PROVIDER=file` | `tenants_secrets.json` | Local dev, Docker testing |
| **Vault Provider** | `TENANCY_SECRETS_PROVIDER=vault` | HashiCorp Vault KV v2 engine | Production Kubernetes / Cloud |

---

## Writing a Custom Provider (e.g., AWS Secrets Manager)

To fetch tenant secrets from AWS Secrets Manager:

### 1. Create the Provider Class
In `config/tenancy_secrets.py`:

```python
import json
import boto3
from schemas.tenancy import TenantSecretConfig
from config.tenancy_secrets import BaseTenancySecretsProvider

class AwsSecretsManagerProvider(BaseTenancySecretsProvider):
    def __init__(self, region_name: str = "us-east-1") -> None:
        self.client = boto3.client("secretsmanager", region_name=region_name)

    async def get_tenant_secret(self, tenant_id: str) -> TenantSecretConfig | None:
        secret_name = f"fastkitty/tenants/{tenant_id}"
        try:
            response = self.client.get_secret_value(SecretId=secret_name)
            data = json.loads(response["SecretString"])
            return TenantSecretConfig.model_validate(data)
        except self.client.exceptions.ResourceNotFoundException:
            return None

    async def get_all_tenant_secrets(self) -> dict[str, TenantSecretConfig]:
        # Implementation to list and fetch all tenant secrets for startup validation
        ...
```

### 2. Register the Provider
Add your new provider to the factory in `config/tenancy_secrets.py`:

```python
PROVIDER_REGISTRY = {
    "file": FileTenancySecretsProvider,
    "vault": VaultTenancySecretsProvider,
    "aws": AwsSecretsManagerProvider,
}
```

### 3. Switch via Environment Variable
Update your `.env`:

```bash
TENANCY_SECRETS_PROVIDER=aws
```

FastKitty will now dynamically pull tenant database credentials from AWS Secrets Manager without touching any route, service, or model code.
