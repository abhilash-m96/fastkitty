"""Unit tests for database dependency helpers and service wiring."""

from contextlib import asynccontextmanager
from unittest.mock import Mock
from unittest.mock import MagicMock
from starlette.requests import Request
from fastapi import FastAPI
import pytest

from api.deps.db import get_blog_posts_service, get_db
from api.deps.tenancy import get_tenant_db_context
from db.tenancy_strategy import TenantDBContext
from schemas.tenancy import DatabaseConfig, TenantConfig, TenantSecrets
from services.blog_posts_service import BlogPostsService


@pytest.mark.asyncio
async def test_get_db_delegates_to_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass the resolved tenant context through to the selected strategy."""
    tenant_context = TenantDBContext(
        tenant_id="tenant_1",
        db_config=DatabaseConfig(
            host="localhost",
            port=5432,
            username="user",
            password="password",
            database_name="db",
        ),
    )
    session = Mock(name="session")
    request = MagicMock(spec=Request)
    request.app = FastAPI()
    captured: list[TenantDBContext] = []

    @asynccontextmanager
    async def fake_get_session(resolved_tenant_context: TenantDBContext):
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


def test_get_tenant_db_context_bundles_tenant_id_and_db() -> None:
    """Bundle tenant_id and db_config into a TenantDBContext."""
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

    context = get_tenant_db_context(tenant_secrets)

    assert context.tenant_id == "tenant_1"
    assert context.db_config == tenant_secrets.database_config


def test_get_blog_posts_service_wraps_session() -> None:
    """Construct the blog post service with the injected DB session."""
    db = Mock(name="db-session")

    service = get_blog_posts_service(db)

    assert isinstance(service, BlogPostsService)
    assert service.db is db
