from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional
from schemas.tenant_config import TenantConfig
from schemas.config_provider_connection import FileConnectionData
from functools import lru_cache
import json


class ProviderType(str, Enum):
    """Enum for different provider types."""

    FILE = "file"


class TenantConfigProvider(ABC):
    """Abstract base class for tenant configuration providers."""

    @abstractmethod
    def get_config(self, tenant_id: str) -> Optional[TenantConfig]:
        """Get configuration for a specific tenant."""
        raise NotImplementedError

    @abstractmethod
    def reload(self) -> None:
        """Reload configurations from the source."""
        raise NotImplementedError


class JSONFileTenantConfigProvider(TenantConfigProvider):
    """Tenant configuration provider that reads from a JSON file."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    @lru_cache(maxsize=100)
    def get_config(self, tenant_id: str) -> Optional[TenantConfig]:
        """Get configuration for a specific tenant."""
        with open(self.file_path, "r") as f:
            data = json.load(f)
            tenant_config_data = data.get(tenant_id)
            return TenantConfig(**tenant_config_data) if tenant_config_data else None

    def reload(self) -> None:
        # TODO: Implement reload logic
        pass
