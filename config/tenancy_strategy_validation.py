from collections.abc import Iterable
from config.settings import Settings
from config.tenancy_providers import TenancyConfigProvider
from config.tenancy_providers_factory import (
    TenancyConfigProviderFactory,
    TenancySecretsProviderFactory,
)
from schemas.tenancy import DatabaseConfig, TenancyDBStrategy


def validate_database_config_for_strategy(
    db_config: DatabaseConfig,
    strategy: TenancyDBStrategy,
    tenant_id: str | None = None,
) -> None:
    """Validate the DB payload shape required by the selected tenancy strategy."""
    if strategy == "schema" and not db_config.schema_name:
        tenant_prefix = f"Tenant '{tenant_id}' " if tenant_id else ""
        raise ValueError(
            f"{tenant_prefix}must define database_config.schema_name when "
            "TENANCY_DB_STRATEGY='schema'"
        )


def _iter_known_tenant_ids(config_provider: TenancyConfigProvider) -> Iterable[str]:
    try:
        tenants = config_provider.get_tenants()
    except NotImplementedError:
        return ()

    return (tenant.tenant_id for tenant in tenants)


def validate_tenancy_strategy_startup(settings: Settings) -> None:
    """
    Fail fast when the selected strategy cannot be supported by the configured
    provider wiring or discoverable tenant payloads.
    """
    config_provider = TenancyConfigProviderFactory.create(
        settings.TENANCY_CONFIG_CONNECTION
    )
    secrets_provider = TenancySecretsProviderFactory.create(
        settings.TENANCY_SECRETS_CONNECTION
    )

    seen_schemas: dict[str, str] = {}
    for tenant_id in _iter_known_tenant_ids(config_provider):
        tenant_secrets = secrets_provider.get_secrets(tenant_id)
        if tenant_secrets is None:
            raise ValueError(
                f"Tenant '{tenant_id}' is configured in tenancy config but has no matching secrets entry in tenancy secrets provider."
            )
        validate_database_config_for_strategy(
            tenant_secrets.database_config,
            settings.TENANCY_DB_STRATEGY,
            tenant_id=tenant_id,
        )
        if settings.TENANCY_DB_STRATEGY == "schema":
            schema_name = tenant_secrets.database_config.schema_name
            if schema_name:
                if schema_name in seen_schemas:
                    raise ValueError(
                        f"Duplicate schema_name '{schema_name}' detected: used by both '{seen_schemas[schema_name]}' and '{tenant_id}'. Each tenant must have a unique schema_name when TENANCY_DB_STRATEGY='schema'."
                    )
                seen_schemas[schema_name] = tenant_id
