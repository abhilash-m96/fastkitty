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


def _build_config_provider_connection(provider_type: ProviderType, settings: Settings) -> ConfigProviderConnectionData:
    if provider_type == ProviderType.FILE:
        return FileConnectionData(file_path=settings.TENANT_CONFIG_FILE_PATH)
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")


def get_tenant_config(
    tenant_id: str = Depends(get_tenant_id), settings=Depends(get_settings)
) -> TenantConfig:
    """
    Get tenant configuration.
    This is the key dependency that provides tenant context.
    """

    tenancy_config_provider = settings.TENANCY_CONFIG_PROVIDER
    connection_data = _build_config_provider_connection(tenancy_config_provider, settings)
    tenancy_service = TenancyService(provider_type=tenancy_config_provider, provider_connection_data=connection_data)

    # TODO raise HTTP exceptions based on errors
    config = tenancy_service.get_tenant_config(tenant_id=tenant_id)

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

    db_uri = (
        tenant_config.database_config.database_uri
        if tenant_config.database_config.database_uri
        else (
            f"{tenant_config.database_config.dialect}://{tenant_config.database_config.username}:"
            f"{tenant_config.database_config.password}@"
            f"{tenant_config.database_config.host}:"
            f"{tenant_config.database_config.port}/"
            f"{tenant_config.database_config.database_name}"
        )
    )

    yield from create_session(
        db_uri=db_uri,
        pool_size=tenant_config.database_config.database_pool_size,
        max_overflow=tenant_config.database_config.database_max_overflow,
        pool_recycle=tenant_config.database_config.database_pool_recycle,
        pool_pre_ping=tenant_config.database_config.database_pool_pre_ping,
    )
