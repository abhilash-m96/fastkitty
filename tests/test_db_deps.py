"""Unit tests for database dependency helpers and service wiring."""

from unittest.mock import Mock

from api.deps.db import build_db_uri, get_blog_posts_service, get_db
from schemas.tenancy import DatabaseConfig, TenantSecrets
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

    assert build_db_uri(config) == "postgresql://user:password@localhost:5432/db"


def test_get_db_delegates_to_create_session(monkeypatch: object) -> None:
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
    captured: dict[str, object] = {}

    def fake_create_session(**kwargs: object):
        captured.update(kwargs)
        yield session

    monkeypatch.setattr("api.deps.db.create_session", fake_create_session)

    yielded_session = next(get_db(tenant_secrets))

    assert yielded_session is session
    assert captured == {
        "db_uri": "postgresql://user:password@localhost:5432/db",
        "pool_size": 10,
        "max_overflow": 10,
        "pool_recycle": 3600,
        "pool_pre_ping": True,
    }


def test_get_blog_posts_service_wraps_session() -> None:
    """Construct the blog post service with the injected DB session."""
    db = Mock(name="db-session")

    service = get_blog_posts_service(db)

    assert isinstance(service, BlogPostsService)
    assert service.db is db
