import pytest

from config.settings import (
    HCConsulTenancyConfigConnection,
    HCVaultTenancySecretsConnection,
    TenancyConfigFileConnection,
    TenancySecretsFileConnection,
)
from config.tenancy_providers import (
    FileTenancyConfigProvider,
    FileTenancySecretsProvider,
    HCConsulTenancyConfigProvider,
    HCVaultTenancySecretsProvider,
)
from config.tenancy_providers_factory import (
    TenancyConfigProviderFactory,
    TenancySecretsProviderFactory,
)


def test_config_provider_factory_creates_file_provider() -> None:
    provider = TenancyConfigProviderFactory.create(
        TenancyConfigFileConnection(file_path="tenants.json")
    )

    assert isinstance(provider, FileTenancyConfigProvider)
    assert provider.file_path == "tenants.json"


def test_config_provider_factory_creates_consul_provider(monkeypatch: object) -> None:
    class FakeConsulProvider:
        def __init__(self, url: str, token: str | None, consul_prefix: str):
            self.url = url
            self.token = token
            self.consul_prefix = consul_prefix

    monkeypatch.setattr(
        "config.tenancy_providers_factory.HCConsulTenancyConfigProvider",
        FakeConsulProvider,
    )

    provider = TenancyConfigProviderFactory.create(
        HCConsulTenancyConfigConnection(
            url="https://consul.example.com",
            token="token",
            consul_prefix="tenants/config/",
        )
    )

    assert isinstance(provider, FakeConsulProvider)
    assert provider.url == "https://consul.example.com"
    assert provider.token == "token"
    assert provider.consul_prefix == "tenants/config/"


def test_config_provider_factory_rejects_unsupported_connection() -> None:
    class UnsupportedConnection:
        type = "unsupported"

    with pytest.raises(ValueError, match="Unsupported config provider: 'unsupported'"):
        TenancyConfigProviderFactory.create(UnsupportedConnection())


def test_secrets_provider_factory_creates_file_provider() -> None:
    provider = TenancySecretsProviderFactory.create(
        TenancySecretsFileConnection(file_path="secrets.json")
    )

    assert isinstance(provider, FileTenancySecretsProvider)
    assert provider.file_path == "secrets.json"


def test_secrets_provider_factory_creates_vault_provider(monkeypatch: object) -> None:
    class FakeVaultProvider:
        def __init__(self, url: str, token: str, vault_kv_path: str):
            self.url = url
            self.token = token
            self.vault_kv_path = vault_kv_path

    monkeypatch.setattr(
        "config.tenancy_providers_factory.HCVaultTenancySecretsProvider",
        FakeVaultProvider,
    )

    provider = TenancySecretsProviderFactory.create(
        HCVaultTenancySecretsConnection(
            url="https://vault.example.com",
            token="token",
            vault_kv_path="secret/data/tenants/{tenant_id}",
        )
    )

    assert isinstance(provider, FakeVaultProvider)
    assert provider.url == "https://vault.example.com"
    assert provider.token == "token"
    assert provider.vault_kv_path == "secret/data/tenants/{tenant_id}"


def test_secrets_provider_factory_rejects_unsupported_connection() -> None:
    class UnsupportedConnection:
        type = "unsupported"

    with pytest.raises(ValueError, match="Unsupported secrets provider: 'unsupported'"):
        TenancySecretsProviderFactory.create(UnsupportedConnection())
