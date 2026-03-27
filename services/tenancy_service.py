from config.tenancy_providers import (
    TenancyConfigProvider,
    TenancySecretsProvider,
)
from schemas.tenancy import TenantConfig, TenantSecrets, TenantMetadata


class TenancyConfigService:
    """Service to manage tenancy configuration operations."""

    def __init__(self, tenancy_config_provider: TenancyConfigProvider):
        self._provider = tenancy_config_provider

    # TODO remove this from here and add it to a high level tenancy service separate from config or secrets
    def list_tenants(self) -> list[TenantMetadata]:
        """List all tenants metadata."""
        tenants_metadata: list[TenantMetadata] = self._provider.get_tenants()
        return tenants_metadata

    def get_tenant_config(self, tenant_id: str) -> TenantConfig:
        """Retrieve tenant configuration."""
        config = self._provider.get_config(tenant_id)

        # TODO implement custom exceptions?
        if not config:
            raise ValueError(f"Tenant '{tenant_id}' not found or not configured")

        return config


class TenancySecretsService:
    """Service to manage tenancy secrets operations."""

    def __init__(self, tenancy_secrets_provider: TenancySecretsProvider):
        self._provider = tenancy_secrets_provider

    def get_tenant_secrets(self, tenant_id: str) -> TenantSecrets:
        """Retrieve tenant secrets."""
        secrets = self._provider.get_secrets(tenant_id)

        if not secrets:
            raise ValueError(
                f"Tenant '{tenant_id}' secrets not found or not configured"
            )

        return secrets
