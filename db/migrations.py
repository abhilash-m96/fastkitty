import asyncio
import logging

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from config.settings import get_settings
from config.tenancy_providers_factory import (
    TenancyConfigProviderFactory,
    TenancySecretsProviderFactory,
)
from db.tenancy_strategy import _normalize_schema_name
import models  # noqa: F401 - ensures all models are registered on Base.metadata
from models.base import Base
from schemas.tenancy import TenantMetadata
from services.tenancy_service import TenancyConfigService, TenancySecretsService

logger = logging.getLogger("alembic.env")
target_metadata = Base.metadata


def get_x_argument(context: object, key: str) -> str | None:
    """Read custom argument passed via -x key=value."""
    x_args = getattr(context, "get_x_argument", lambda as_dictionary=True: {})(
        as_dictionary=True
    )
    return x_args.get(key)


def resolve_tenants_and_secrets(
    target_tenant: str | None = None,
) -> tuple[list[TenantMetadata], TenancySecretsService | None]:
    """Resolve active tenants and secrets provider service."""
    settings = get_settings()
    try:
        config_provider = TenancyConfigProviderFactory.create(
            settings.TENANCY_CONFIG_CONNECTION
        )
        secrets_provider = TenancySecretsProviderFactory.create(
            settings.TENANCY_SECRETS_CONNECTION
        )
        config_service = TenancyConfigService(config_provider)
        secrets_service = TenancySecretsService(secrets_provider)

        all_tenants = config_service.list_tenants()
        if target_tenant:
            matching = [t for t in all_tenants if t.tenant_id == target_tenant]
            if not matching:
                raise ValueError(
                    f"Tenant '{target_tenant}' not found in tenancy configuration"
                )
            return matching, secrets_service
        return [t for t in all_tenants if t.is_active], secrets_service
    except ValueError:
        raise
    except Exception as exc:
        logger.warning("Could not resolve tenants from providers: %s", exc)
        return [], None


def get_fallback_url(context: object) -> str:
    config = getattr(context, "config", None)
    url = config.get_main_option("sqlalchemy.url") if config else None
    if not url or url.startswith("driver://"):
        raise ValueError(
            "No valid database URL found. Configure tenants or set sqlalchemy.url in alembic.ini"
        )
    return url


def run_migrations_offline(context: object) -> None:
    """Run migrations in 'offline' mode."""
    settings = get_settings()
    target_tenant = get_x_argument(context, "tenant")
    override_url = get_x_argument(context, "url")
    strategy = settings.TENANCY_DB_STRATEGY

    if override_url:
        context.configure(  # type: ignore[attr-defined]
            url=override_url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():  # type: ignore[attr-defined]
            context.run_migrations()  # type: ignore[attr-defined]
        return

    tenants, secrets_service = resolve_tenants_and_secrets(target_tenant)

    if strategy == "row":
        url = None
        if tenants and secrets_service:
            secrets = secrets_service.get_tenant_secrets(tenants[0].tenant_id)
            url = secrets.database_config.database_uri
        if not url:
            url = get_fallback_url(context)

        context.configure(  # type: ignore[attr-defined]
            url=url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():  # type: ignore[attr-defined]
            context.run_migrations()  # type: ignore[attr-defined]

    elif strategy == "schema":
        if not tenants or not secrets_service:
            raise ValueError("Schema strategy requires tenant configuration")
        shared_url = secrets_service.get_tenant_secrets(
            tenants[0].tenant_id
        ).database_config.database_uri
        for tenant in tenants:
            secrets = secrets_service.get_tenant_secrets(tenant.tenant_id)
            schema_name = _normalize_schema_name(secrets.database_config)
            context.configure(  # type: ignore[attr-defined]
                url=shared_url,
                target_metadata=target_metadata,
                literal_binds=True,
                dialect_opts={"paramstyle": "named"},
                version_table="alembic_version",
                version_table_schema=schema_name,
            )
            with context.begin_transaction():  # type: ignore[attr-defined]
                context.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}";')  # type: ignore[attr-defined]
                context.execute(f'SET search_path TO "{schema_name}", public;')  # type: ignore[attr-defined]
                context.run_migrations()  # type: ignore[attr-defined]
                context.execute("RESET search_path;")  # type: ignore[attr-defined]

    elif strategy == "database":
        if not tenants or not secrets_service:
            raise ValueError("Database strategy requires tenant configuration")
        for tenant in tenants:
            secrets = secrets_service.get_tenant_secrets(tenant.tenant_id)
            db_uri = secrets.database_config.database_uri
            context.configure(  # type: ignore[attr-defined]
                url=db_uri,
                target_metadata=target_metadata,
                literal_binds=True,
                dialect_opts={"paramstyle": "named"},
                version_table="alembic_version",
            )
            with context.begin_transaction():  # type: ignore[attr-defined]
                context.run_migrations()  # type: ignore[attr-defined]
    else:
        raise ValueError(f"Unknown tenancy strategy: {strategy!r}")


def run_single_db_migrations(
    context: object,
    connection: Connection,
    version_table_schema: str | None = None,
) -> None:
    context.configure(  # type: ignore[attr-defined]
        connection=connection,
        target_metadata=target_metadata,
        version_table="alembic_version",
        version_table_schema=version_table_schema,
    )
    with context.begin_transaction():  # type: ignore[attr-defined]
        context.run_migrations()  # type: ignore[attr-defined]


def run_schema_migrations(
    context: object,
    connection: Connection,
    tenants: list[TenantMetadata],
    secrets_service: TenancySecretsService,
) -> None:
    for tenant in tenants:
        secrets = secrets_service.get_tenant_secrets(tenant.tenant_id)
        schema_name = _normalize_schema_name(secrets.database_config)
        logger.info(
            "Migrating schema '%s' for tenant '%s'...",
            schema_name,
            tenant.tenant_id,
        )
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
        connection.execute(text(f'SET search_path TO "{schema_name}", public'))
        try:
            run_single_db_migrations(
                context, connection, version_table_schema=schema_name
            )
        finally:
            connection.execute(text("RESET search_path"))


async def run_async_migrations(context: object) -> None:
    settings = get_settings()
    override_url = get_x_argument(context, "url")
    target_tenant = get_x_argument(context, "tenant")
    strategy = settings.TENANCY_DB_STRATEGY

    if override_url:
        engine = create_async_engine(override_url, poolclass=pool.NullPool)
        async with engine.connect() as connection:
            await connection.run_sync(
                lambda conn: run_single_db_migrations(context, conn)
            )
        await engine.dispose()
        return

    tenants, secrets_service = resolve_tenants_and_secrets(target_tenant)

    if strategy == "row":
        url = None
        if tenants and secrets_service:
            secrets = secrets_service.get_tenant_secrets(tenants[0].tenant_id)
            url = secrets.database_config.database_uri
        if not url:
            url = get_fallback_url(context)

        engine = create_async_engine(url, poolclass=pool.NullPool)
        async with engine.connect() as connection:
            await connection.run_sync(
                lambda conn: run_single_db_migrations(context, conn)
            )
        await engine.dispose()

    elif strategy == "schema":
        if not tenants or not secrets_service:
            raise ValueError("Schema strategy requires tenant configuration")
        first_secrets = secrets_service.get_tenant_secrets(tenants[0].tenant_id)
        shared_url = first_secrets.database_config.database_uri

        engine = create_async_engine(shared_url, poolclass=pool.NullPool)
        async with engine.connect() as connection:
            await connection.run_sync(
                lambda conn: run_schema_migrations(
                    context, conn, tenants, secrets_service
                )
            )
        await engine.dispose()

    elif strategy == "database":
        if not tenants or not secrets_service:
            raise ValueError("Database strategy requires tenant configuration")
        for tenant in tenants:
            secrets = secrets_service.get_tenant_secrets(tenant.tenant_id)
            db_uri = secrets.database_config.database_uri
            logger.info("Migrating database for tenant '%s'...", tenant.tenant_id)
            engine = create_async_engine(db_uri, poolclass=pool.NullPool)
            async with engine.connect() as connection:
                await connection.run_sync(
                    lambda conn: run_single_db_migrations(context, conn)
                )
            await engine.dispose()
    else:
        raise ValueError(f"Unknown tenancy strategy: {strategy!r}")


def run_migrations_online(context: object) -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations(context))
