from pydantic import BaseModel, Field
from typing import Any, Optional, Self


class DatabaseConfig(BaseModel):
    """Schema for database configuration."""

    dialect: str = Field(
        default="postgresql", description="Database dialect (e.g., postgresql, mysql)"
    )
    host: str = Field(..., description="Database host address")
    port: int = Field(..., description="Database port number")
    username: str = Field(..., description="Database username")
    password: str = Field(..., description="Database password")
    database_name: str = Field(..., description="Name of the database")
    database_uri: Optional[str] = Field(None, description="Database connection URI")
    schema_name: Optional[str] = Field(
        None, description="Schema name for schema-per-tenant strategy"
    )
    pool_pre_ping: bool = Field(
        default=True, description="Whether to pre-ping the database"
    )
    pool_size: int = Field(default=10, description="The size of the database pool")
    max_overflow: int = Field(
        default=10, description="The maximum number of connections to allow in the pool"
    )
    pool_recycle: int = Field(
        default=3600,
        description="The number of seconds to recycle the database connections",
    )


FeatureConfig = dict[
    str, Any
]  # Free-form per-feature config map. Keys/values are user-defined.


class TenantConfig(BaseModel):
    """Schema for tenant configuration."""

    tenant_id: str = Field(..., description="The ID of the tenant")
    display_name: str = Field(..., description="The display name of the tenant")
    is_active: bool = Field(..., description="Whether the tenant is active")
    features: Optional[dict[str, FeatureConfig]] = Field(
        default=None,
        description="Per-feature config keyed by feature name; values are user-defined",
    )


class TenantSecrets(BaseModel):
    """Schema for tenant secret configuration."""

    tenant_id: str = Field(..., description="The ID of the tenant")
    database_config: DatabaseConfig = Field(
        ..., description="The database secret configuration for the tenant"
    )


class TenantMetadata(BaseModel):
    """Schema for tenant metadata."""

    tenant_id: str = Field(..., description="The ID of the tenant")
    display_name: str = Field(..., description="The display name of the tenant")
    is_active: bool = Field(..., description="Whether the tenant is active")
