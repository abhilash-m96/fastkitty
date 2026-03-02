from config.tenancy_config_providers import (
    ProviderType,
    TenantConfigProvider,
    JSONFileTenantConfigProvider,
    DatabaseTenantConfigProvider,
)
from schemas.config_provider_connection import (
    ConfigProviderConnectionData,
    FileConnectionData,
    DatabaseConnectionData,
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

    @staticmethod
    def create_database_config_provider(
        connection_data: DatabaseConnectionData,
    ) -> DatabaseTenantConfigProvider:
        """Create a database-based provider."""
        return DatabaseTenantConfigProvider(db_uri=connection_data.db_uri)

    @classmethod
    def create(
        cls, provider_type: ProviderType, connection_data: ConfigProviderConnectionData
    ) -> TenantConfigProvider:
        """
        Create a config provider based on type.
        
        Note: The connection_data must be validated against the correct schema before passing here
        or cast appropriately. In a real app, strict type checking should occur before this call.
        
        Args:
            provider_type: Type of provider to create
            connection_data: Provider-specific connection data object

        Returns:
            TenantConfigProvider instance

        Raises:
            ValueError: If invalid provider_type or config mismatch
        """
        if provider_type == ProviderType.FILE:
            if not isinstance(connection_data, FileConnectionData):
                # Try to cast if it's a generic dict/model
                try:
                    connection_data = FileConnectionData(**connection_data.model_dump())
                except Exception:
                    raise ValueError(f"Invalid connection data for provider type {provider_type}")
            return cls.create_json_file_config_provider(connection_data=connection_data)

        elif provider_type == ProviderType.DATABASE:
            if not isinstance(connection_data, DatabaseConnectionData):
                # Try to cast
                try:
                    connection_data = DatabaseConnectionData(**connection_data.model_dump())
                except Exception:
                    raise ValueError(f"Invalid connection data for provider type {provider_type}")
            return cls.create_database_config_provider(connection_data=connection_data)

        else:
            raise ValueError(f"Unknown provider type: {provider_type}")
