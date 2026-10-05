import logging
from fastapi import Depends, Header, HTTPException, Request, status

from config.settings import get_settings, Settings
from config.telemetry import enrich_span_with_tenant
from config.tenancy_providers_factory import (
    TenancyConfigProviderFactory,
    TenancySecretsProviderFactory,
)
from db.tenancy_strategy import TenantDBContext
from schemas.tenancy import FeatureConfig, TenantConfig, TenantSecrets
from services.tenancy_service import TenancyConfigService, TenancySecretsService

logger = logging.getLogger(__name__)


def get_tenant_id(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> str:
    """Extract tenant ID from request header."""
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant ID is required (X-Tenant-ID header missing)",
        )
    return x_tenant_id.lower()


def get_tenancy_config_service(settings: Settings = Depends(get_settings)):
    tenancy_config_connection_data = settings.TENANCY_CONFIG_CONNECTION
    tenancy_config_provider = TenancyConfigProviderFactory.create(
        connection=tenancy_config_connection_data
    )
    return TenancyConfigService(tenancy_config_provider=tenancy_config_provider)


def get_tenant_config(
    tenant_id: str = Depends(get_tenant_id),
    tenancy_config_service: TenancyConfigService = Depends(get_tenancy_config_service),
) -> TenantConfig:
    """
    Get tenant configuration.
    This is the key dependency that provides tenant context.
    """

    # TODO raise HTTP exceptions based on errors
    config = tenancy_config_service.get_tenant_config(tenant_id=tenant_id)

    if not config:
        logger.warning("Tenant '%s' not found or not configured", tenant_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found or not configured",
        )

    logger.debug("Resolved tenant configuration for '%s' (%s)", config.tenant_id, config.display_name)
    enrich_span_with_tenant(tenant_id=config.tenant_id, display_name=config.display_name)
    return config


def require_active_tenant(
    tenant_config: TenantConfig = Depends(get_tenant_config),
) -> TenantConfig:
    if not tenant_config.is_active:
        logger.warning("Rejected inactive tenant: %s", tenant_config.tenant_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant '{tenant_config.tenant_id}' is not active!",
        )
    return tenant_config


def get_tenancy_secrets_service(settings: Settings = Depends(get_settings)):
    tenancy_secrets_connection_data = settings.TENANCY_SECRETS_CONNECTION
    tenancy_secrets_provider = TenancySecretsProviderFactory.create(
        connection=tenancy_secrets_connection_data
    )
    return TenancySecretsService(tenancy_secrets_provider=tenancy_secrets_provider)


def get_tenant_secrets(
    tenant_config: TenantConfig = Depends(require_active_tenant),
    tenancy_secrets_service: TenancySecretsService = Depends(
        get_tenancy_secrets_service
    ),
) -> TenantSecrets:
    """
    Get tenant secrets.
    Only reached if tenant exists and is active.
    """
    secrets: TenantSecrets = tenancy_secrets_service.get_tenant_secrets(
        tenant_id=tenant_config.tenant_id
    )
    if not secrets:
        logger.warning("Secrets for tenant '%s' not found", tenant_config.tenant_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Secrets for tenant '{tenant_config.tenant_id}' not found",
        )
    return secrets


def get_tenant_db_context(
    tenant_secrets: TenantSecrets = Depends(get_tenant_secrets),
) -> TenantDBContext:
    """Bundle tenant config and secrets into a single context for DB strategies."""
    return TenantDBContext(
        tenant_id=tenant_secrets.tenant_id,
        db_config=tenant_secrets.database_config,
    )


def get_feature_config(key: str | None = None):
    """
    Dependency factory to fetch a feature config by key.
    If key is not provided, the current route name is used.
    The route name can be set explicitly or will be the default route name provided by FastAPI.
    """

    def _get_feature_config(
        request: Request,
        tenant_config: TenantConfig = Depends(require_active_tenant),
    ) -> FeatureConfig | None:
        feature_key = key or request.scope["route"].name
        features = tenant_config.features or {}
        return features.get(feature_key)

    return _get_feature_config
