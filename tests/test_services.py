"""Unit tests for service-layer behavior with mocked collaborators."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from models.posts import BlogPost
from schemas.posts import BlogPostCreate, BlogPostUpdate
from schemas.tenancy import TenantConfig, TenantMetadata, TenantSecrets
from services.blog_posts_service import BlogPostsService
from services.tenancy_service import TenancyConfigService, TenancySecretsService


def test_blog_posts_service_lists_posts_for_user() -> None:
    """Query and return posts filtered to the requested author."""
    db = Mock()
    query = db.query.return_value
    filter_result = query.filter.return_value
    ordered_result = filter_result.order_by.return_value
    posts = [Mock(spec=BlogPost)]
    ordered_result.all.return_value = posts

    service = BlogPostsService(db)

    assert service.list_posts(user_id="user-1") == posts
    db.query.assert_called_once_with(BlogPost)
    ordered_result.all.assert_called_once_with()


def test_blog_posts_service_get_post_returns_first_match() -> None:
    """Return the first post matching the requested ID and author."""
    db = Mock()
    query = db.query.return_value
    filtered = query.filter.return_value
    post = Mock(spec=BlogPost)
    filtered.first.return_value = post

    service = BlogPostsService(db)

    assert service.get_post(10, user_id="user-1") is post


def test_blog_posts_service_create_post_persists_and_refreshes() -> None:
    """Create a new post entity and persist it through the session."""
    db = Mock()
    service = BlogPostsService(db)
    payload = BlogPostCreate(title="Post", content="Body")

    post = service.create_post(payload, user_id="user-1")

    assert isinstance(post, BlogPost)
    assert post.title == "Post"
    assert post.content == "Body"
    assert post.author == "user-1"
    db.add.assert_called_once_with(post)
    db.commit.assert_called_once_with()
    db.refresh.assert_called_once_with(post)


def test_blog_posts_service_update_post_ignores_unknown_author_field() -> None:
    """Ignore author changes when applying partial update payloads."""
    db = Mock()
    service = BlogPostsService(db)
    post = BlogPost(
        id=1,
        title="Old title",
        content="Old body",
        author="user-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    payload = BlogPostUpdate.model_construct(title="New title", author="user-2")

    updated = service.update_post(post, payload)

    assert updated is post
    assert post.title == "New title"
    assert post.author == "user-1"
    db.commit.assert_called_once_with()
    db.refresh.assert_called_once_with(post)


def test_blog_posts_service_delete_post_removes_and_commits() -> None:
    """Delete the given post and commit the session transaction."""
    db = Mock()
    service = BlogPostsService(db)
    post = Mock(spec=BlogPost)

    service.delete_post(post)

    db.delete.assert_called_once_with(post)
    db.commit.assert_called_once_with()


def test_tenancy_config_service_lists_tenants_from_provider() -> None:
    """Pass through tenant metadata listings from the config provider."""
    provider = Mock()
    tenants = [
        TenantMetadata(
            tenant_id="tenant_1",
            display_name="Tenant One",
            is_active=True,
        )
    ]
    provider.get_tenants.return_value = tenants

    service = TenancyConfigService(provider)

    assert service.list_tenants() == tenants


def test_tenancy_config_service_raises_for_missing_config() -> None:
    """Raise a clear error when a tenant config cannot be found."""
    provider = Mock()
    provider.get_config.return_value = None

    service = TenancyConfigService(provider)

    with pytest.raises(
        ValueError, match="Tenant 'tenant_1' not found or not configured"
    ):
        service.get_tenant_config("tenant_1")


def test_tenancy_config_service_returns_provider_config() -> None:
    """Return the provider result unchanged for configured tenants."""
    provider = Mock()
    tenant = TenantConfig(
        tenant_id="tenant_1",
        display_name="Tenant One",
        is_active=True,
        features=None,
    )
    provider.get_config.return_value = tenant

    service = TenancyConfigService(provider)

    assert service.get_tenant_config("tenant_1") == tenant


def test_tenancy_secrets_service_raises_for_missing_secrets() -> None:
    """Raise a clear error when tenant secrets are absent."""
    provider = Mock()
    provider.get_secrets.return_value = None

    service = TenancySecretsService(provider)

    with pytest.raises(
        ValueError, match="Tenant 'tenant_1' secrets not found or not configured"
    ):
        service.get_tenant_secrets("tenant_1")


def test_tenancy_secrets_service_returns_provider_secrets() -> None:
    """Return tenant secrets unchanged when the provider supplies them."""
    provider = Mock()
    secrets = TenantSecrets.model_validate(
        {
            "tenant_id": "tenant_1",
            "database_config": {
                "host": "localhost",
                "port": 5432,
                "username": "user",
                "password": "password",
                "database_name": "db",
            },
        }
    )
    provider.get_secrets.return_value = secrets

    service = TenancySecretsService(provider)

    assert service.get_tenant_secrets("tenant_1") == secrets
