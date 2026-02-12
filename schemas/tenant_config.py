from pydantic import BaseModel, Field
from typing import Optional


class DatabaseConfig(BaseModel):
    """Schema for database configuration."""
    dialect: str = Field(default="postgresql", description="Database dialect (e.g., postgresql, mysql)")
    host: str = Field(..., description="Database host address")
    port: int = Field(..., description="Database port number")
    username: str = Field(..., description="Database username")
    password: str = Field(..., description="Database password")
    database_name: str = Field(..., description="Name of the database")
    database_uri: Optional[str] = Field(None, description="Database connection URI")
    database_pool_pre_ping: bool = Field(
        default=True, description="Whether to pre-ping the database"
    )
    database_pool_size: int = Field(
        default=10, description="The size of the database pool"
    )
    database_max_overflow: int = Field(
        default=10, description="The maximum number of connections to allow in the pool"
    )
    database_pool_recycle: int = Field(
        default=3600,
        description="The number of seconds to recycle the database connections",
    )


class TenantConfig(BaseModel):
    """Schema for tenant configuration."""

    tenant_id: str = Field(..., description="The ID of the tenant")
    display_name: str = Field(..., description="The display name of the tenant")
    database_config: DatabaseConfig = Field(
        ..., description="The database configuration for the tenant"
    )
    is_active: bool = Field(..., description="Whether the tenant is active")
