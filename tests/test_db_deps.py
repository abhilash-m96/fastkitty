"""Unit tests for database dependency helpers and service wiring."""

import pytest
from contextlib import asynccontextmanager
from unittest.mock import Mock, AsyncMock

from api.deps.db import get_blog_posts_service, get_db
from db.session import PoolConfig
from schemas.tenancy import DatabaseConfig, TenantSecrets
from services.blog_posts_service import BlogPostsService


@pytest.mark.asyncio
async def test_get_db_delegates_to_create_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass the resolved tenant DB settings through to session creation."""
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
    session = Mock(name="session")
    captured: list[PoolConfig] = []

    @asynccontextmanager
    async def fake_create_session(config: PoolConfig):
        captured.append(config)
        yield session

    monkeypatch.setattr("api.deps.db.create_session", fake_create_session)

    generator = get_db(tenant_secrets)
    yielded_session = await anext(generator)

    assert yielded_session is session
    assert len(captured) == 1
    assert captured[0] == PoolConfig(
        db_uri="postgresql+asyncpg://user:password@localhost:5432/db",
        pool_size=10,
        max_overflow=10,
        pool_recycle=3600,
        pool_pre_ping=True,
    )
    await generator.aclose()


def test_get_blog_posts_service_wraps_session() -> None:
    """Construct the blog post service with the injected DB session."""
    db = Mock(name="db-session")

    service = get_blog_posts_service(db)

    assert isinstance(service, BlogPostsService)
    assert service.db is db
