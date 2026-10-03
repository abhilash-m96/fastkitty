from dataclasses import dataclass
from typing import Any, Literal, Optional, Self
from pydantic import BaseModel, Field, model_validator


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
    schema_name: Optional[str] = Field(
        default=None,
        description="Tenant schema name, used in schema-per-tenant strategy",
    )
    database_uri: str = Field(default="", description="Database connection URI")
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

    @model_validator(mode="after")
    def set_uri(self) -> Self:
        """
        Normalise dialect to asyncpg and build the URI if not explicitly provided.

        Handles three common dialect spellings:
          postgresql, postgres -> postgresql+asyncpg
        Any pre-supplied URI has its scheme normalised the same way.
        Pool config fields are intentionally excluded from the URI — they
        are passed separately to the engine.
        """
        # Normalise dialect
        if self.dialect in ("postgresql", "postgres"):
            self.dialect = "postgresql+asyncpg"

        if self.database_uri:
            # Normalise a pre-supplied URI's scheme
            for old in ("postgresql://", "postgres://"):
                if self.database_uri.startswith(old):
                    self.database_uri = self.database_uri.replace(
                        old, "postgresql+asyncpg://", 1
                    )
                    break
        else:
            self.database_uri = (
                f"{self.dialect}://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/{self.database_name}"
            )
        return self


FeatureConfig = dict[
    str, Any
]  # Free-form per-feature config map. Keys/values are user-defined.


TenancyDBStrategy = Literal["database", "schema", "row"]


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
