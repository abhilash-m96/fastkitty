from config.tenancy_providers import (
    TenancyConfigProvider,
    FileTenancyConfigProvider,
    HCConsulTenancyConfigProvider,
    TenancySecretsProvider,
    FileTenancySecretsProvider,
    HCVaultTenancySecretsProvider,
)
from config.settings import (
    TenancyConfigConnection,
    TenancySecretsConnection,
    TenancyConfigFileConnection,
    HCConsulTenancyConfigConnection,
    TenancySecretsFileConnection,
    HCVaultTenancySecretsConnection,
)


class TenancyConfigProviderFactory:
    """
    Factory class to create the appropriate config provider.
    """

    @staticmethod
    def _create_file_config_provider(
        connection_data: TenancyConfigFileConnection,
    ) -> FileTenancyConfigProvider:
        """Create a file-based provider."""
        return FileTenancyConfigProvider(file_path=connection_data.file_path)

    @staticmethod
    def _create_hc_consul_config_provider(
        connection_data: HCConsulTenancyConfigConnection,
    ) -> HCConsulTenancyConfigProvider:
        """Create a HashiCorp Consul-based provider."""
        return HCConsulTenancyConfigProvider(
            url=connection_data.url,
            token=connection_data.token,
            consul_prefix=connection_data.consul_prefix,
        )

    @classmethod
    def create(cls, connection: TenancyConfigConnection) -> TenancyConfigProvider:
        if isinstance(connection, TenancyConfigFileConnection):
            return cls._create_file_config_provider(connection)
        if isinstance(connection, HCConsulTenancyConfigConnection):
            return cls._create_hc_consul_config_provider(connection)
        else:
            raise ValueError(f"Unsupported config provider: {connection.type!r}")


class TenancySecretsProviderFactory:
    """
    Factory class to create the appropriate secrets provider.
    """

    @staticmethod
    def _create_file_secrets_provider(
        connection_data: TenancySecretsFileConnection,
    ) -> FileTenancySecretsProvider:
        """Create a file-based provider."""
        return FileTenancySecretsProvider(file_path=connection_data.file_path)

    @staticmethod
    def _create_hc_vault_secrets_provider(
        connection_data: HCVaultTenancySecretsConnection,
    ) -> HCVaultTenancySecretsProvider:
        """Create a HashiCorp Vault-based provider."""
        return HCVaultTenancySecretsProvider(
            url=connection_data.url,
            token=connection_data.token,
            vault_kv_path=connection_data.vault_kv_path,
        )

    @classmethod
    def create(cls, connection: TenancySecretsConnection) -> TenancySecretsProvider:
        if isinstance(connection, TenancySecretsFileConnection):
            return cls._create_file_secrets_provider(connection)
        if isinstance(connection, HCVaultTenancySecretsConnection):
            return cls._create_hc_vault_secrets_provider(connection)
        else:
            raise ValueError(f"Unsupported secrets provider: {connection.type!r}")
