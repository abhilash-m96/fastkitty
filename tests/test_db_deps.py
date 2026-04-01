"""Unit tests for database dependency helpers and service wiring."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from api.deps.db import get_blog_posts_service, get_db
from api.deps.tenancy import get_tenant_context
from db.tenancy_strategy import TenantContext
from schemas.tenancy import DatabaseConfig, TenantConfig, TenantSecrets
from services.blog_posts_service import BlogPostsService


@pytest.mark.asyncio
async def test_get_db_delegates_to_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    captured: list[TenantContext] = []

    @asynccontextmanager
    async def fake_get_session(resolved_tenant_context: TenantContext):
        captured.append(resolved_tenant_context)
        yield session

    fake_strategy = Mock(name="strategy")
    fake_strategy.get_session = fake_get_session
    monkeypatch.setattr(
        "api.deps.db.get_app_tenancy_strategy", lambda app: fake_strategy
    )

    generator = get_db(request, tenant_context)
    yielded_session = await anext(generator)

    assert yielded_session is session
    assert len(captured) == 1
    assert captured[0] is tenant_context

    await generator.aclose()


def test_get_tenant_context_bundles_config_and_secrets() -> None:
    """Bundle config and secrets into a TenantContext."""
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
