from collections.abc import Iterable
from config.settings import Settings
from config.tenancy_providers import TenancyConfigProvider
from config.tenancy_providers_factory import (
    TenancyConfigProviderFactory,
    TenancySecretsProviderFactory,
)
from schemas.tenancy import _mask_url, DatabaseConfig, TenancyDBStrategy


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

    strategy = settings.TENANCY_DB_STRATEGY
    seen_databases: dict[tuple[str, int, str], tuple[str, str]] = {}
    first_shared_tenant: str | None = None
    first_shared_uri: str | None = None
    first_pool_settings: tuple[int, int, int, bool] | None = None
    seen_schemas: dict[str, str] = {}

    for tenant_id in _iter_known_tenant_ids(config_provider):
        tenant_secrets = secrets_provider.get_secrets(tenant_id)
        if tenant_secrets is None:
            raise ValueError(
                f"Tenant '{tenant_id}' is configured in tenancy config but has no matching secrets entry in tenancy secrets provider."
            )
        db_config = tenant_secrets.database_config
        validate_database_config_for_strategy(
            db_config,
            strategy,
            tenant_id=tenant_id,
        )

        db_uri = db_config.database_uri
        if strategy == "database":
            db_key = (db_config.host.lower(), db_config.port, db_config.database_name)
            if db_key in seen_databases:
                first_tenant, first_uri = seen_databases[db_key]
                masked_uri = _mask_url(db_uri)
                raise ValueError(
                    f"Duplicate database_uri '{masked_uri}' detected: used by both '{first_tenant}' and '{tenant_id}'. Each tenant must have a unique database_uri when TENANCY_DB_STRATEGY='database'."
                )
            seen_databases[db_key] = (tenant_id, db_uri)

        elif strategy in ("row", "schema"):
            current_pool_settings = (
                db_config.pool_size,
                db_config.max_overflow,
                db_config.pool_recycle,
                db_config.pool_pre_ping,
            )
            if first_shared_uri is None:
                first_shared_uri = db_uri
                first_shared_tenant = tenant_id
                first_pool_settings = current_pool_settings
            else:
                if db_uri != first_shared_uri:
                    masked_first = _mask_url(first_shared_uri)
                    masked_current = _mask_url(db_uri)
                    raise ValueError(
                        f"Conflicting database_uri detected for {strategy} strategy: '{first_shared_tenant}' uses '{masked_first}' but '{tenant_id}' uses '{masked_current}'. All tenants must share the same database_uri when TENANCY_DB_STRATEGY='{strategy}'."
                    )
                if current_pool_settings != first_pool_settings:
                    raise ValueError(
                        f"Conflicting pool settings detected for {strategy} strategy between '{first_shared_tenant}' and '{tenant_id}' for database URL '{_mask_url(db_uri)}'. All tenants must have identical pool settings when TENANCY_DB_STRATEGY='{strategy}'."
                    )

            if strategy == "schema":
                from db.tenancy_strategy import _normalize_schema_name

                _normalize_schema_name(db_config)
                schema_name = db_config.schema_name
                if schema_name:
                    canonical_schema = schema_name.lower()[:63]
                    if canonical_schema in seen_schemas:
                        first_tenant = seen_schemas[canonical_schema]
                        raise ValueError(
                            f"Duplicate schema_name '{schema_name}' detected: used by both '{first_tenant}' and '{tenant_id}'. Each tenant must have a unique schema_name when TENANCY_DB_STRATEGY='schema'."
                        )
                    seen_schemas[canonical_schema] = tenant_id
