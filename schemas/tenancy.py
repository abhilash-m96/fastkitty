import re
import urllib.parse
from typing import Any, Literal, Optional, Self
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.engine import make_url


def _mask_url(url: str) -> str:
    """Mask credentials in a database connection URL for safe logging and repr."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


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
    ssl: Optional[str | bool] = Field(
        default=None,
        description="SSL mode for database connection (e.g., 'require', 'prefer', 'verify-full', or True)",
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

    def __repr__(self) -> str:
        masked_uri = _mask_url(self.database_uri) if self.database_uri else ""
        return (
            f"DatabaseConfig(dialect={self.dialect!r}, host={self.host!r}, "
            f"port={self.port!r}, username={self.username!r}, password='***', "
            f"database_name={self.database_name!r}, schema_name={self.schema_name!r}, "
            f"database_uri={masked_uri!r}, pool_pre_ping={self.pool_pre_ping}, "
            f"pool_size={self.pool_size}, max_overflow={self.max_overflow}, "
            f"pool_recycle={self.pool_recycle}, ssl={self.ssl!r})"
        )

    def __str__(self) -> str:
        return repr(self)

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
            if self.ssl is not None and "ssl=" not in self.database_uri:
                ssl_val = (
                    "require"
                    if self.ssl is True
                    else ("disable" if self.ssl is False else str(self.ssl))
                )
                delimiter = "&" if "?" in self.database_uri else "?"
                self.database_uri = f"{self.database_uri}{delimiter}ssl={ssl_val}"
        else:
            quoted_user = urllib.parse.quote(self.username, safe="")
            quoted_pass = urllib.parse.quote(self.password, safe="")
            uri = (
                f"{self.dialect}://{quoted_user}:{quoted_pass}"
                f"@{self.host}:{self.port}/{self.database_name}"
            )
            if self.ssl is not None:
                ssl_val = (
                    "require"
                    if self.ssl is True
                    else ("disable" if self.ssl is False else str(self.ssl))
                )
                uri = f"{uri}?ssl={ssl_val}"
            self.database_uri = uri
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
