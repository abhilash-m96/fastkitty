"""Unit tests for database dependency helpers and service wiring."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from api.deps.db import build_db_uri, get_blog_posts_service, get_db
from db.tenancy_strategy import TenantContext
from schemas.tenancy import DatabaseConfig, TenantConfig, TenantSecrets
from services.blog_posts_service import BlogPostsService


def test_build_db_uri_prefers_existing_database_uri() -> None:
    """Prefer the direct URI when tenant secrets already provide one."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="user",
        password="password",
        database_name="db",
        database_uri="sqlite:///tmp.db",
    )

    assert build_db_uri(config) == "sqlite:///tmp.db"


def test_build_db_uri_falls_back_to_computed_uri() -> None:
    """Compose the URI from discrete DB fields when no URI is present."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="user",
        password="password",
        database_name="db",
    )
    config.database_uri = None

    assert build_db_uri(config) == "postgresql+asyncpg://user:password@localhost:5432/db"


@pytest.mark.asyncio
async def test_get_db_delegates_to_create_session(monkeypatch: object) -> None:
    """Pass the resolved tenant context through to the selected strategy."""
    tenant_context = TenantContext(
        tenant_id="tenant_1",
        tenant_config=TenantConfig(
            tenant_id="tenant_1",
            display_name="Tenant One",
            is_active=True,
        ),
        tenant_secrets=TenantSecrets(
            tenant_id="tenant_1",
            database_config=DatabaseConfig(
                host="localhost",
                port=5432,
                username="user",
                password="password",
                database_name="db",
            ),
        ),
    )
    session = Mock(name="session")
    request = SimpleNamespace(app=SimpleNamespace())
    fake_strategy = Mock(name="strategy")

    async def fake_get_session(resolved_tenant_context: TenantContext):
        assert resolved_tenant_context is tenant_context
        yield session

    fake_strategy.get_session = fake_get_session
    monkeypatch.setattr("api.deps.db.get_app_tenancy_strategy", lambda app: fake_strategy)

    generator = get_db(request, tenant_context)
    yielded_session = await anext(generator)

    assert yielded_session is session
    await generator.aclose()


def test_get_tenant_context_bundles_config_and_secrets() -> None:
    from api.deps.tenancy import get_tenant_context

    tenant_config = TenantConfig(
        tenant_id="tenant_1",
        display_name="Tenant One",
        is_active=True,
    )
    tenant_secrets = TenantSecrets(
        tenant_id="tenant_1",
        database_config=DatabaseConfig(
            host="localhost",
            port=5432,
            username="user",
            password="password",
            database_name="db",
        ),
    )

    context = get_tenant_context(tenant_config, tenant_secrets)

    assert context.tenant_id == "tenant_1"
    assert context.tenant_config is tenant_config
    assert context.tenant_secrets is tenant_secrets


def test_get_blog_posts_service_wraps_session() -> None:
    """Construct the blog post service with the injected DB session."""
    db = Mock(name="db-session")

    service = get_blog_posts_service(db)

    assert isinstance(service, BlogPostsService)
    assert service.db is db
