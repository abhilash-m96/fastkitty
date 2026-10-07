from abc import ABC, abstractmethod
import json
import os
import re
from urllib.parse import urlparse

import consul
import hvac
from pydantic import SecretStr
from schemas.tenancy import TenantConfig, TenantSecrets, TenantMetadata

_TENANT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


class TenantNotFoundError(Exception):
    """Raised when a requested tenant's configuration or secrets cannot be found."""

    pass


def validate_tenant_id(tenant_id: str) -> str:
    """Validate that tenant_id adheres to a safe identifier format without path traversal."""
    if not isinstance(tenant_id, str):
        raise ValueError("tenant_id must be a string")
    normalized = tenant_id.strip().lower()
    if not _TENANT_ID_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"Invalid tenant_id format: '{tenant_id}'. Must match ^[a-z0-9][a-z0-9_-]{{0,62}}$"
        )
    return normalized


class TenancyConfigProvider(ABC):
    """Abstract base class for tenant configuration providers."""

    @abstractmethod
    def get_tenants(self):
        raise NotImplementedError

    @abstractmethod
    def get_config(self, tenant_id: str, fresh: bool = False) -> TenantConfig | None:
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
        tenants = []
        for key, tenant in data.items():
            inner_id = tenant.get("tenant_id")
            if inner_id != key:
                raise ValueError(
                    f"Tenancy config key '{key}' does not match inner tenant_id '{inner_id}'"
                )
            tenants.append(TenantMetadata(**tenant))
        return tenants

    def get_config(self, tenant_id: str, fresh: bool = False) -> TenantConfig | None:
        # TODO handle caching based on `fresh`
        """Get configuration for a specific tenant."""
        tenant_id = validate_tenant_id(tenant_id)
        data = self._get_all_config()
        tenant_config_data = data.get(tenant_id)
        if not tenant_config_data:
            return None
        inner_id = tenant_config_data.get("tenant_id")
        if inner_id != tenant_id:
            raise ValueError(
                f"Tenancy config key '{tenant_id}' does not match inner tenant_id '{inner_id}'"
            )
        return TenantConfig(**tenant_config_data)


class DBTenancyConfigProvider(TenancyConfigProvider):
    """Tenant configuration provider that reads from a DB."""

    pass


class HCConsulTenancyConfigProvider(TenancyConfigProvider):
    """Tenant configuration provider that reads from HashiCorp Consul KV."""

    def __init__(
        self,
        url: str,
        token: str | SecretStr | None,
        consul_prefix: str,
        timeout: float = 10.0,
    ):
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.hostname:
            raise ValueError("Consul url must include scheme and host")
        port = parsed.port or (443 if parsed.scheme == "https" else 8500)
        raw_token = token.get_secret_value() if isinstance(token, SecretStr) else token
        self._client = consul.Consul(
            host=parsed.hostname,
            port=port,
            scheme=parsed.scheme,
            token=raw_token,
            timeout=timeout,
        )
        self._prefix = consul_prefix

    def _key_for_tenant(self, tenant_id: str) -> str:
        prefix = self._prefix.rstrip("/") + "/"
        return f"{prefix}{tenant_id}"

    def get_tenants(self) -> list[TenantMetadata]:
        raise NotImplementedError("Consul list_tenants not supported")

    def get_config(self, tenant_id: str, fresh: bool = False) -> TenantConfig:
        # TODO handle caching based on `fresh`
        tenant_id = validate_tenant_id(tenant_id)
        key = self._key_for_tenant(tenant_id)
        _index, data = self._client.kv.get(key)
        if not data or data.get("Value") is None:
            raise TenantNotFoundError(
                f"Tenant '{tenant_id}' not found or not configured"
            )

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
    def get_secrets(self, tenant_id: str) -> TenantSecrets | None:
        """Get secrets for a specific tenant."""
        raise NotImplementedError


class FileTenancySecretsProvider(TenancySecretsProvider):
    """Tenant secret provider that reads from a JSON file."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def get_secrets(self, tenant_id: str, fresh: bool = True) -> TenantSecrets | None:
        # TODO handle caching based on fresh value
        """Get secrets for a specific tenant."""
        tenant_id = validate_tenant_id(tenant_id)

        if not os.path.exists(self.file_path):
            example_path = (
                self.file_path.replace(".json", ".example.json")
                if not self.file_path.endswith(".example.json")
                else self.file_path
            )
            if os.path.exists(example_path):
                raise FileNotFoundError(
                    f"Secrets file '{self.file_path}' not found. "
                    f"Please copy '{example_path}' to '{self.file_path}' and configure your tenant credentials."
                )
            raise FileNotFoundError(f"Secrets file '{self.file_path}' not found.")

        with open(self.file_path, "r") as f:
            data = json.load(f)
            tenant_secrets_data = data.get(tenant_id)
            if not tenant_secrets_data:
                return None
            inner_id = tenant_secrets_data.get("tenant_id")
            if inner_id != tenant_id:
                raise ValueError(
                    f"Tenancy secrets key '{tenant_id}' does not match inner tenant_id '{inner_id}'"
                )
            return TenantSecrets(**tenant_secrets_data)


class GCPTenancySecretsProvider(TenancySecretsProvider):
    """Tenant secret provider that reads from Google Cloud Secret Manager."""

    pass


class HCVaultTenancySecretsProvider(TenancySecretsProvider):
    """Tenant secret provider that reads from HashiCorp Vault KV v2."""

    def __init__(
        self,
        url: str,
        token: str | SecretStr,
        vault_kv_path: str,
        timeout: float = 10.0,
    ):
        raw_token = token.get_secret_value() if isinstance(token, SecretStr) else token
        self._client = hvac.Client(url=url, token=raw_token, timeout=timeout)
        self._vault_kv_path = vault_kv_path

    def get_secrets(self, tenant_id: str, fresh: bool = True) -> TenantSecrets:
        # TODO handle caching based on fresh value
        tenant_id = validate_tenant_id(tenant_id)
        if "{tenant_id}" in self._vault_kv_path:
            path = self._vault_kv_path.format(tenant_id=tenant_id)
        else:
            path = self._vault_kv_path

        data = self._client.read(path)
        if not data or "data" not in data:
            raise TenantNotFoundError(
                f"Tenant '{tenant_id}' secrets not found or not configured"
            )

        # Support both KV v1 (data) and KV v2 (data.data) response formats.
        payload = data["data"]
        if isinstance(payload, dict) and "data" in payload:
            payload = payload["data"]
        return TenantSecrets(**payload)
