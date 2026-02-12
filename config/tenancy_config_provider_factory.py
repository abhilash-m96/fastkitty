from config.tenancy_config_providers import (
    ProviderType,
    TenantConfigProvider,
    JSONFileTenantConfigProvider,
)
from schemas.config_provider_connection import (
    ConfigProviderConnectionData,
    FileConnectionData,
)


class TenantConfigProviderFactory:
    """
    Factory class to create the appropriate config provider.
    Each provider type can have its own configuration requirements.
    """

    @staticmethod
    def create_json_file_config_provider(
        connection_data: FileConnectionData,
    ) -> JSONFileTenantConfigProvider:
        """Create a file-based provider."""
        return JSONFileTenantConfigProvider(file_path=connection_data.file_path)

    @classmethod
    def create(
        cls, provider_type: ProviderType, connection_data: ConfigProviderConnectionData
    ) -> TenantConfigProvider:
        """
        Create a config provider based on type

        Args:
            provider_type: Type of provider to create
            connection_data: Provider-specific connection data object

        Returns:
            TenantConfigProvider instance

        Raises:
            ValueError: If invalid provider_type or config
        """
        if provider_type == ProviderType.FILE:
            return cls.create_json_file_config_provider(connection_data=connection_data)
        else:
            raise ValueError(f"Unknown provider type: {provider_type}")
