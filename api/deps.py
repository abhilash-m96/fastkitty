from db.session import create_session
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional, Generator
from config.tenancy_config_provider_factory import ProviderType
from config.settings import get_settings, Settings
from schemas.tenant_config import TenantConfig
from schemas.config_provider_connection import (
    ConfigProviderConnectionData,
    FileConnectionData,
    DatabaseConnectionData,
)
from services.tenancy_service import TenancyService


def get_tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> str:
    """Extract tenant ID from request header."""
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant ID is required (X-Tenant-ID header missing)",
        )
    return x_tenant_id.lower()


def _build_config_provider_connection(provider_type: str, settings: Settings) -> ConfigProviderConnectionData:
    if provider_type == ProviderType.FILE:
        return FileConnectionData(file_path=settings.TENANT_CONFIG_FILE_PATH)
    elif provider_type == ProviderType.DATABASE:
        return DatabaseConnectionData(db_uri=settings.TENANT_CATALOG_DB_URI)
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")


def get_tenant_config(
    tenant_id: str = Depends(get_tenant_id),
    settings: Settings = Depends(get_settings),
) -> TenantConfig:
    """
    Get tenant configuration.
    This is the key dependency that provides tenant context.
    """
    
    # Ensure provider_type is matched correctly (str to Enum if needed)
    # settings.TENANCY_CONFIG_PROVIDER is a string, ProviderType is an Enum(str)
    # Direct comparison works for StrEnum but let's be safe
    try:
        tenancy_config_provider = ProviderType(settings.TENANCY_CONFIG_PROVIDER)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid configuration: Unknown provider type '{settings.TENANCY_CONFIG_PROVIDER}'"
        )

    try:
        connection_data = _build_config_provider_connection(tenancy_config_provider, settings)
        tenancy_service = TenancyService(provider_type=tenancy_config_provider, provider_connection_data=connection_data)
        config = tenancy_service.get_tenant_config(tenant_id=tenant_id)
    except Exception as e:
        # Catch configuration errors or missing tenants
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tenancy service error: {str(e)}"
        )

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found or not configured",
        )

    if not config.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant '{tenant_id}' is not active",
        )

    return config


def get_db(
    tenant_config: TenantConfig = Depends(get_tenant_config),
) -> Generator[Session, None, None]:
    """Get a database session for the current tenant."""

    if tenant_config.database_config.database_uri:
        db_uri = tenant_config.database_config.database_uri
    else:
        # Construct URI from components
        db_uri = (
            f"{tenant_config.database_config.dialect}://{tenant_config.database_config.username}:"
            f"{tenant_config.database_config.password}@"
            f"{tenant_config.database_config.host}:"
            f"{tenant_config.database_config.port}/"
            f"{tenant_config.database_config.database_name}"
        )

    yield from create_session(
        db_uri=db_uri,
        pool_size=tenant_config.database_config.database_pool_size,
        max_overflow=tenant_config.database_config.database_max_overflow,
        pool_recycle=tenant_config.database_config.database_pool_recycle,
        pool_pre_ping=tenant_config.database_config.database_pool_pre_ping,
    )
