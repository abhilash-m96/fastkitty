from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional
from schemas.tenant_config import TenantConfig, DatabaseConfig
from functools import lru_cache
import json
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


class ProviderType(str, Enum):
    """Enum for different provider types."""
    FILE = "file"
    DATABASE = "database"


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
        try:
            with open(self.file_path, "r") as f:
                data = json.load(f)
                tenant_config_data = data.get(tenant_id)
                return TenantConfig(**tenant_config_data) if tenant_config_data else None
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def reload(self) -> None:
        self.get_config.cache_clear()


class DatabaseTenantConfigProvider(TenantConfigProvider):
    """
    Tenant configuration provider that reads from a generic SQL database.
    Assumes a 'tenants' table exists with columns matching the TenantConfig schema.
    """

    def __init__(self, db_uri: str):
        self.db_uri = db_uri
        # In a real app, manage the engine lifecycle better (e.g. separate connection pool)
        # For this provider, we create a dedicated engine.
        self.engine = create_engine(db_uri)

    @lru_cache(maxsize=100)
    def get_config(self, tenant_id: str) -> Optional[TenantConfig]:
        """Get configuration for a specific tenant from the database."""
        # Query assumes a table structure that maps to our config needs
        # We select specific columns to map to the Pydantic model
        query = text(
            "SELECT tenant_id, display_name, is_active, "
            "db_dialect, db_host, db_port, db_username, db_password, db_name, db_uri "
            "FROM tenants WHERE tenant_id = :tenant_id"
        )
        
        try:
            with self.engine.connect() as connection:
                # Execute and fetch one row as a mapping (dict-like)
                result = connection.execute(query, {"tenant_id": tenant_id}).mappings().first()
                
                if not result:
                    return None
                
                # Construct DatabaseConfig dictionary from result
                # Note: We map column names (db_*) to schema fields
                db_config_data = {
                    "dialect": result["db_dialect"],
                    "host": result["db_host"],
                    "port": result["db_port"],
                    "username": result["db_username"],
                    "password": result["db_password"],
                    "database_name": result["db_name"],
                    "database_uri": result.get("db_uri") # Optional
                }
                
                # Construct main TenantConfig object
                return TenantConfig(
                    tenant_id=result["tenant_id"],
                    display_name=result["display_name"],
                    is_active=result["is_active"],
                    database_config=DatabaseConfig(**db_config_data)
                )
        except SQLAlchemyError as e:
            # Log error properly in production
            # print(f"Database error fetching tenant config: {e}")
            return None

    def reload(self) -> None:
        """Clear the cache to force re-fetching from DB."""
        self.get_config.cache_clear()
