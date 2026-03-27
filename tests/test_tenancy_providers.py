import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from config.tenancy_providers import (
    FileTenancyConfigProvider,
    FileTenancySecretsProvider,
    HCConsulTenancyConfigProvider,
    HCVaultTenancySecretsProvider,
)


def _tenant_config_payload() -> dict[str, dict[str, object]]:
    return {
        "tenant_1": {
            "tenant_id": "tenant_1",
            "display_name": "Tenant One",
            "is_active": True,
            "features": {"greet": {"message": "Hello {tenant_name}!"}},
        }
    }


def _tenant_secrets_payload() -> dict[str, dict[str, object]]:
    return {
        "tenant_1": {
            "tenant_id": "tenant_1",
            "database_config": {
                "host": "localhost",
                "port": 5432,
                "username": "user",
                "password": "password",
                "database_name": "tenant_db",
            },
        }
    }


def test_file_config_provider_returns_tenant_config(tmp_path: Path) -> None:
    config_path = tmp_path / "tenants.json"
    config_path.write_text(json.dumps(_tenant_config_payload()))
    provider = FileTenancyConfigProvider(str(config_path))

    config = provider.get_config("tenant_1")

    assert config.tenant_id == "tenant_1"
    assert config.display_name == "Tenant One"
    assert config.features == {"greet": {"message": "Hello {tenant_name}!"}}


def test_file_config_provider_returns_tenants_metadata(tmp_path: Path) -> None:
    config_path = tmp_path / "tenants.json"
    config_path.write_text(json.dumps(_tenant_config_payload()))
    provider = FileTenancyConfigProvider(str(config_path))

    tenants = provider.get_tenants()

    assert len(tenants) == 1
    assert tenants[0].tenant_id == "tenant_1"
    assert tenants[0].display_name == "Tenant One"
    assert tenants[0].is_active is True


def test_file_secrets_provider_returns_tenant_secrets(tmp_path: Path) -> None:
    secrets_path = tmp_path / "secrets.json"
    secrets_path.write_text(json.dumps(_tenant_secrets_payload()))
    provider = FileTenancySecretsProvider(str(secrets_path))

    secrets = provider.get_secrets("tenant_1")

    assert secrets.tenant_id == "tenant_1"
    assert secrets.database_config.database_uri == (
        "postgresql://user:password@localhost:5432/tenant_db"
    )


def test_consul_provider_requires_url_with_scheme_and_host() -> None:
    with pytest.raises(ValueError, match="Consul url must include scheme and host"):
        HCConsulTenancyConfigProvider(
            url="consul.example.com",
            token=None,
            consul_prefix="tenants/config/",
        )


def test_consul_provider_builds_tenant_key_from_prefix(monkeypatch: object) -> None:
    fake_client = Mock()
    monkeypatch.setattr("config.tenancy_providers.consul.Consul", lambda **_: fake_client)
    provider = HCConsulTenancyConfigProvider(
        url="https://consul.example.com",
        token="token",
        consul_prefix="tenants/config",
    )

    assert provider._key_for_tenant("tenant_1") == "tenants/config/tenant_1"


def test_consul_provider_reads_and_decodes_bytes_payload(monkeypatch: object) -> None:
    fake_client = Mock()
    fake_client.kv.get.return_value = (
        1,
        {"Value": json.dumps(_tenant_config_payload()["tenant_1"]).encode("utf-8")},
    )
    monkeypatch.setattr("config.tenancy_providers.consul.Consul", lambda **_: fake_client)
    provider = HCConsulTenancyConfigProvider(
        url="https://consul.example.com",
        token="token",
        consul_prefix="tenants/config/",
    )

    config = provider.get_config("tenant_1")

    fake_client.kv.get.assert_called_once_with("tenants/config/tenant_1")
    assert config.tenant_id == "tenant_1"


def test_consul_provider_raises_for_missing_value(monkeypatch: object) -> None:
    fake_client = Mock()
    fake_client.kv.get.return_value = (1, None)
    monkeypatch.setattr("config.tenancy_providers.consul.Consul", lambda **_: fake_client)
    provider = HCConsulTenancyConfigProvider(
        url="https://consul.example.com",
        token=None,
        consul_prefix="tenants/config/",
    )

    with pytest.raises(ValueError, match="Tenant 'tenant_1' not found or not configured"):
        provider.get_config("tenant_1")


def test_consul_provider_raises_for_invalid_json(monkeypatch: object) -> None:
    fake_client = Mock()
    fake_client.kv.get.return_value = (1, {"Value": "{invalid-json"})
    monkeypatch.setattr("config.tenancy_providers.consul.Consul", lambda **_: fake_client)
    provider = HCConsulTenancyConfigProvider(
        url="https://consul.example.com",
        token=None,
        consul_prefix="tenants/config/",
    )

    with pytest.raises(ValueError, match="Consul tenant config is not valid JSON"):
        provider.get_config("tenant_1")


def test_consul_provider_list_tenants_is_not_supported(monkeypatch: object) -> None:
    monkeypatch.setattr("config.tenancy_providers.consul.Consul", lambda **_: Mock())
    provider = HCConsulTenancyConfigProvider(
        url="https://consul.example.com",
        token=None,
        consul_prefix="tenants/config/",
    )

    with pytest.raises(NotImplementedError, match="Consul list_tenants not supported"):
        provider.get_tenants()


def test_vault_provider_formats_path_with_tenant_id(monkeypatch: object) -> None:
    fake_client = Mock()
    fake_client.read.return_value = {
        "data": {
            "data": _tenant_secrets_payload()["tenant_1"],
        }
    }
    monkeypatch.setattr("config.tenancy_providers.hvac.Client", lambda **_: fake_client)
    provider = HCVaultTenancySecretsProvider(
        url="https://vault.example.com",
        token="token",
        vault_kv_path="secret/data/tenants/{tenant_id}",
    )

    secrets = provider.get_secrets("tenant_1")

    fake_client.read.assert_called_once_with("secret/data/tenants/tenant_1")
    assert secrets.tenant_id == "tenant_1"


def test_vault_provider_supports_v1_response_shape(monkeypatch: object) -> None:
    fake_client = Mock()
    fake_client.read.return_value = {
        "data": _tenant_secrets_payload()["tenant_1"],
    }
    monkeypatch.setattr("config.tenancy_providers.hvac.Client", lambda **_: fake_client)
    provider = HCVaultTenancySecretsProvider(
        url="https://vault.example.com",
        token="token",
        vault_kv_path="secret/tenant",
    )

    secrets = provider.get_secrets("tenant_1")

    fake_client.read.assert_called_once_with("secret/tenant")
    assert secrets.tenant_id == "tenant_1"


def test_vault_provider_raises_for_missing_data(monkeypatch: object) -> None:
    fake_client = Mock()
    fake_client.read.return_value = None
    monkeypatch.setattr("config.tenancy_providers.hvac.Client", lambda **_: fake_client)
    provider = HCVaultTenancySecretsProvider(
        url="https://vault.example.com",
        token="token",
        vault_kv_path="secret/data/tenants/{tenant_id}",
    )

    with pytest.raises(
        ValueError, match="Tenant 'tenant_1' secrets not found or not configured"
    ):
        provider.get_secrets("tenant_1")
