from config.tenancy_config_provider_factory import TenantConfigProviderFactory
from config.tenancy_config_providers import ProviderType, TenantConfigProvider
from schemas.config_provider_connection import ConfigProviderConnectionData
from schemas.tenant_config import TenantConfig


class TenancyService:
    """Service to manage tenancy operations."""

    def __init__(
        self,
        provider_type: ProviderType,
        provider_connection_data: ConfigProviderConnectionData,
    ):
        self.provider_type = provider_type
        self.provider_connection_data = provider_connection_data
        self.tenancy_config_provider_factory = TenantConfigProviderFactory()
        self._provider: TenantConfigProvider = None


    def list_tenants(self) -> list[str]:
        """List all tenant IDs."""
        pass

    def get_tenant_config(self, tenant_id: str) -> TenantConfig:
        """Retrieve tenant configuration."""
        tenancy_config_provider = self.tenancy_config_provider_factory.create(
            provider_type=self.provider_type,
            connection_data=self.provider_connection_data
        )
        self._provider = tenancy_config_provider
        config = self._provider.get_config(tenant_id)

        # TODO implement custom exceptions?
        if not config:
            raise ValueError(f"Tenant '{tenant_id}' not found or not configured")

        if not config.is_active:
            raise PermissionError(f"Tenant '{tenant_id}' is not active")

        return config
