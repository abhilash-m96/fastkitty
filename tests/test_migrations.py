"""Automated multi-strategy tests for Alembic database migrations."""

from unittest.mock import MagicMock, call, patch

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from config.settings import Settings
from db.migrations import (
    resolve_tenants_and_secrets,
    run_async_migrations,
    run_schema_migrations,
)
from schemas.tenancy import DatabaseConfig, TenantMetadata, TenantSecrets
from services.tenancy_service import TenancyConfigService, TenancySecretsService


class FakeAsyncConnection:
    def __init__(self) -> None:
        self.raw_connection = MagicMock()

    async def run_sync(self, fn, *args, **kwargs):
        return fn(self.raw_connection, *args, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class FakeAsyncEngine:
    def __init__(self, url: str) -> None:
        self.url = url
        self.dispose_calls = 0

    def connect(self) -> FakeAsyncConnection:
        return FakeAsyncConnection()

    async def dispose(self) -> None:
        self.dispose_calls += 1


def test_migration_revisions_structure() -> None:
    """Verify that Alembic discovers the initial blog posts migration revision."""
    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    heads = script.get_heads()

    assert heads == ["0001_initial_blog_posts"]
    rev = script.get_revision("0001_initial_blog_posts")
    assert rev is not None
    assert rev.down_revision is None
    assert rev.module.upgrade is not None
    assert rev.module.downgrade is not None


def test_resolve_tenants_and_secrets_filtering() -> None:
    """Verify selective tenant filtering via -x tenant=<tenant_id>."""
    mock_config_service = MagicMock(spec=TenancyConfigService)
    mock_secrets_service = MagicMock(spec=TenancySecretsService)

    mock_config_service.list_tenants.return_value = [
        TenantMetadata(tenant_id="tenant_1", display_name="Tenant 1", is_active=True),
        TenantMetadata(tenant_id="tenant_2", display_name="Tenant 2", is_active=False),
        TenantMetadata(tenant_id="tenant_3", display_name="Tenant 3", is_active=True),
    ]

    with (
        patch("db.migrations.TenancyConfigService", return_value=mock_config_service),
        patch("db.migrations.TenancySecretsService", return_value=mock_secrets_service),
    ):
        # All active tenants when no target specified
        tenants, secrets = resolve_tenants_and_secrets()
        assert secrets is not None
        assert [t.tenant_id for t in tenants] == ["tenant_1", "tenant_3"]

        # Filtered by target_tenant
        tenants, secrets = resolve_tenants_and_secrets(target_tenant="tenant_1")
        assert len(tenants) == 1
        assert tenants[0].tenant_id == "tenant_1"

        # Non-existent tenant raises ValueError
        with pytest.raises(ValueError, match="Tenant 'unknown' not found"):
            resolve_tenants_and_secrets(target_tenant="unknown")


def test_schema_strategy_migration_sequence() -> None:
    """Verify schema strategy executes schema creation, search_path setting, and search_path reset."""
    mock_conn = MagicMock()
    mock_context = MagicMock()
    tenants = [
        TenantMetadata(tenant_id="tenant_1", display_name="Tenant 1", is_active=True),
        TenantMetadata(tenant_id="tenant_2", display_name="Tenant 2", is_active=True),
    ]
    mock_secrets_service = MagicMock(spec=TenancySecretsService)
    mock_secrets_service.get_tenant_secrets.side_effect = [
        TenantSecrets(
            tenant_id="tenant_1",
            database_config=DatabaseConfig(
                host="localhost",
                port=5432,
                username="u",
                password="p",
                database_name="db",
                schema_name="tenant_1_schema",
            ),
        ),
        TenantSecrets(
            tenant_id="tenant_2",
            database_config=DatabaseConfig(
                host="localhost",
                port=5432,
                username="u",
                password="p",
                database_name="db",
                schema_name="tenant_2_schema",
            ),
        ),
    ]

    executed_statements = []

    def fake_execute(statement: object) -> None:
        executed_statements.append(str(statement))

    mock_conn.execute.side_effect = fake_execute

    with patch("db.migrations.run_single_db_migrations") as mock_run_single:
        run_schema_migrations(mock_context, mock_conn, tenants, mock_secrets_service)

    assert mock_run_single.call_count == 2
    mock_run_single.assert_has_calls(
        [
            call(mock_context, mock_conn, version_table_schema="tenant_1_schema"),
            call(mock_context, mock_conn, version_table_schema="tenant_2_schema"),
        ]
    )

    # Verify SQL sequence: CREATE SCHEMA -> SET search_path -> RESET search_path
    assert 'CREATE SCHEMA IF NOT EXISTS "tenant_1_schema"' in executed_statements[0]
    assert 'SET search_path TO "tenant_1_schema", public' in executed_statements[1]
    assert "RESET search_path" in executed_statements[2]
    assert 'CREATE SCHEMA IF NOT EXISTS "tenant_2_schema"' in executed_statements[3]
    assert 'SET search_path TO "tenant_2_schema", public' in executed_statements[4]
    assert "RESET search_path" in executed_statements[5]


@pytest.mark.asyncio
async def test_row_strategy_execution() -> None:
    """Verify live row strategy migration configures alembic context with row database."""
    db_url = "postgresql+asyncpg://shared-db/app"
    created_engines: list[FakeAsyncEngine] = []

    def fake_create_engine(url: str, **kwargs):
        eng = FakeAsyncEngine(url)
        created_engines.append(eng)
        return eng

    mock_context = MagicMock()
    mock_settings = Settings(TENANCY_DB_STRATEGY="row")

    with (
        patch("db.migrations.get_x_argument", side_effect=lambda ctx, k: db_url if k == "url" else None),
        patch("db.migrations.get_settings", return_value=mock_settings),
        patch("db.migrations.create_async_engine", side_effect=fake_create_engine),
    ):
        await run_async_migrations(mock_context)

    assert len(created_engines) == 1
    assert created_engines[0].url == db_url
    assert created_engines[0].dispose_calls == 1
    assert mock_context.configure.called
    assert mock_context.run_migrations.called


@pytest.mark.asyncio
async def test_database_strategy_execution() -> None:
    """Verify database strategy runs migrations for multiple isolated tenant databases."""
    url1 = "postgresql+asyncpg://tenant1-db/app"
    url2 = "postgresql+asyncpg://tenant2-db/app"
    created_engines: list[FakeAsyncEngine] = []

    def fake_create_engine(url: str, **kwargs):
        eng = FakeAsyncEngine(url)
        created_engines.append(eng)
        return eng

    mock_context = MagicMock()
    mock_settings = Settings(TENANCY_DB_STRATEGY="database")
    tenants = [
        TenantMetadata(tenant_id="tenant_1", display_name="Tenant 1", is_active=True),
        TenantMetadata(tenant_id="tenant_2", display_name="Tenant 2", is_active=True),
    ]

    mock_secrets = MagicMock()
    mock_secrets.get_tenant_secrets.side_effect = [
        TenantSecrets(
            tenant_id="tenant_1",
            database_config=DatabaseConfig(
                host="localhost",
                port=5432,
                username="u",
                password="p",
                database_name="t1",
                database_uri=url1,
            ),
        ),
        TenantSecrets(
            tenant_id="tenant_2",
            database_config=DatabaseConfig(
                host="localhost",
                port=5432,
                username="u",
                password="p",
                database_name="t2",
                database_uri=url2,
            ),
        ),
    ]

    with (
        patch("db.migrations.get_x_argument", return_value=None),
        patch("db.migrations.resolve_tenants_and_secrets", return_value=(tenants, mock_secrets)),
        patch("db.migrations.get_settings", return_value=mock_settings),
        patch("db.migrations.create_async_engine", side_effect=fake_create_engine),
    ):
        await run_async_migrations(mock_context)

    assert len(created_engines) == 2
    assert [e.url for e in created_engines] == [url1, url2]
    assert all(e.dispose_calls == 1 for e in created_engines)
    assert mock_context.run_migrations.call_count == 2
