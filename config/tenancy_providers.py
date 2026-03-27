from abc import ABC, abstractmethod
from schemas.tenancy import TenantConfig, TenantSecrets, TenantMetadata
import json
from urllib.parse import urlparse

import consul
import hvac


class TenancyConfigProvider(ABC):
    """Abstract base class for tenant configuration providers."""

    @abstractmethod
    def get_tenants(self):
        raise NotImplementedError

    @abstractmethod
    def get_config(self, tenant_id: str, fresh: bool = False) -> TenantConfig:
        """Get configuration for a specific tenant."""
        raise NotImplementedError


class FileTenancyConfigProvider(TenancyConfigProvider):
    """Tenant configuration provider that reads from a file."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def _get_all_config(self):
        with open(self.file_path, "r") as f:
            data = json.load(f)
        return data

    def get_tenants(self) -> list[TenantMetadata]:
        data = self._get_all_config()
        return [TenantMetadata(**tenant) for tenant in data.values()]

    def get_config(self, tenant_id: str, fresh: bool = False) -> TenantConfig:
        # TODO handle caching based on `fresh`
        """Get configuration for a specific tenant."""
        data = self._get_all_config()
        tenant_config_data = data.get(tenant_id)
        return TenantConfig(**tenant_config_data)


class DBTenancyConfigProvider(TenancyConfigProvider):
    """Tenant configuration provider that reads from a DB."""

    pass


class HCConsulTenancyConfigProvider(TenancyConfigProvider):
    """Tenant configuration provider that reads from HashiCorp Consul KV."""

    def __init__(self, url: str, token: str | None, consul_prefix: str):
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.hostname:
            raise ValueError("Consul url must include scheme and host")
        port = parsed.port or (443 if parsed.scheme == "https" else 8500)
        self._client = consul.Consul(
            host=parsed.hostname,
            port=port,
            scheme=parsed.scheme,
            token=token,
        )
        self._prefix = consul_prefix

    def _key_for_tenant(self, tenant_id: str) -> str:
        prefix = self._prefix.rstrip("/") + "/"
        return f"{prefix}{tenant_id}"

    def get_tenants(self) -> list[TenantMetadata]:
        raise NotImplementedError("Consul list_tenants not supported")

    def get_config(self, tenant_id: str, fresh: bool = False) -> TenantConfig:
        # TODO handle caching based on `fresh`
        key = self._key_for_tenant(tenant_id)
        _index, data = self._client.kv.get(key)
        if not data or data.get("Value") is None:
            raise ValueError(f"Tenant '{tenant_id}' not found or not configured")

        value = data["Value"]
        if isinstance(value, bytes):
            value = value.decode("utf-8")

        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Consul tenant config is not valid JSON") from exc

        return TenantConfig(**payload)


class TenancySecretsProvider(ABC):
    """Abstract base class for tenant secret providers."""

    @abstractmethod
    def get_secrets(self, tenant_id: str) -> TenantSecrets:
        """Get secrets for a specific tenant."""
        raise NotImplementedError


class FileTenancySecretsProvider(TenancySecretsProvider):
    """Tenant secret provider that reads from a JSON file."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def get_secrets(self, tenant_id: str, fresh: bool = True) -> TenantSecrets:
        # TODO handle caching based on fresh value
        """Get secrets for a specific tenant."""
        with open(self.file_path, "r") as f:
            data = json.load(f)
            tenant_secrets_data = data.get(tenant_id)
            return TenantSecrets(**tenant_secrets_data)


class GCPTenancySecretsProvider(TenancySecretsProvider):
    """Tenant secret provider that reads from Google Cloud Secret Manager."""

    pass


class HCVaultTenancySecretsProvider(TenancySecretsProvider):
    """Tenant secret provider that reads from HashiCorp Vault KV v2."""

    def __init__(self, url: str, token: str, vault_kv_path: str):
        self._client = hvac.Client(url=url, token=token)
        self._vault_kv_path = vault_kv_path

    def get_secrets(self, tenant_id: str, fresh: bool = True) -> TenantSecrets:
        # TODO handle caching based on fresh value
        if "{tenant_id}" in self._vault_kv_path:
            path = self._vault_kv_path.format(tenant_id=tenant_id)
        else:
            path = self._vault_kv_path

        data = self._client.read(path)
        if not data or "data" not in data:
            raise ValueError(
                f"Tenant '{tenant_id}' secrets not found or not configured"
            )

        # Support both KV v1 (data) and KV v2 (data.data) response formats.
        payload = data["data"]
        if isinstance(payload, dict) and "data" in payload:
            payload = payload["data"]
        return TenantSecrets(**payload)
