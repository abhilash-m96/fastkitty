"""Route-level tests for tenant-aware hello and blog post endpoints."""

from datetime import UTC, datetime

from api.deps.db import get_blog_posts_service
from api.deps.tenancy import get_tenant_config
from api.deps.user_data import get_user_data
from models.posts import BlogPost


def _blog_post(
    *,
    post_id: int = 1,
    title: str = "Post title",
    content: str = "Post body",
    author: str = "user-123",
) -> BlogPost:
    """Create a lightweight blog post model instance for response assertions."""
    now = datetime.now(UTC)
    return BlogPost(
        id=post_id,
        title=title,
        content=content,
        author=author,
        created_at=now,
        updated_at=now,
    )


def test_hello_uses_feature_message_template(
    client,
    apply_overrides,
    tenant_config,
    header_user_headers,
) -> None:
    """Use feature-config templating when a greet override is defined."""
    apply_overrides(
        {
            get_tenant_config: lambda: tenant_config,
        }
    )

    response = client.get("/v1/hello", headers=header_user_headers)

    assert response.status_code == 200
    assert response.json() == {"message": "Hello Tenant One!"}


def test_hello_falls_back_to_default_message_when_feature_missing(
    client,
    apply_overrides,
    tenant_config,
    header_user_headers,
) -> None:
    """Fall back to the default hello message when feature config is absent."""
    tenant_config.features = None
    apply_overrides({get_tenant_config: lambda: tenant_config})

    response = client.get("/v1/hello", headers=header_user_headers)

    assert response.status_code == 200
    assert response.json() == {"message": "Hello Tenant One!"}


def test_hello_rejects_inactive_tenant(
    client,
    apply_overrides,
    inactive_tenant_config,
    header_user_headers,
) -> None:
    """Block the hello route when the resolved tenant is inactive."""
    apply_overrides({get_tenant_config: lambda: inactive_tenant_config})

    response = client.get("/v1/hello", headers=header_user_headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Tenant 'tenant_2' is not active!"}


def test_hello_requires_tenant_header_without_override(client) -> None:
    """Return a 400 when tenant resolution has no header to read from."""
    response = client.get("/v1/hello")

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Tenant ID is required (X-Tenant-ID header missing)"
    }


def test_create_blog_post_returns_created_post(
    client,
    apply_overrides,
    tenant_config,
    user_payload,
) -> None:
    """Create a blog post for the current user and return the serialized model."""
    post = _blog_post(title="Created post", content="Created body")

    class FakeBlogPostsService:
        async def create_post(self, payload, *, user_id: str):
            assert payload.title == "Created post"
            assert payload.content == "Created body"
            assert user_id == user_payload["user_id"]
            return post

    apply_overrides(
        {
            get_tenant_config: lambda: tenant_config,
            get_blog_posts_service: lambda: FakeBlogPostsService(),
            get_user_data: lambda: user_payload,
        }
    )

    response = client.post(
        "/v1/blog-posts",
        json={"title": "Created post", "content": "Created body"},
        headers={"X-Tenant-ID": "tenant_1"},
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Created post"
    assert response.json()["author"] == "user-123"


def test_list_blog_posts_returns_user_posts(
    client,
    apply_overrides,
    tenant_config,
    user_payload,
) -> None:
    """List blog posts scoped to the current user from the service layer."""
    posts = [
        _blog_post(post_id=1, title="First"),
        _blog_post(post_id=2, title="Second"),
    ]

    class FakeBlogPostsService:
        async def list_posts(self, *, user_id: str):
            assert user_id == user_payload["user_id"]
            return posts

    apply_overrides(
        {
            get_tenant_config: lambda: tenant_config,
            get_blog_posts_service: lambda: FakeBlogPostsService(),
            get_user_data: lambda: user_payload,
        }
    )

    response = client.get("/v1/blog-posts", headers={"X-Tenant-ID": "tenant_1"})

    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["First", "Second"]


def test_get_blog_post_returns_not_found_when_missing(
    client,
    apply_overrides,
    tenant_config,
    user_payload,
) -> None:
    """Return a 404 when the requested blog post does not exist for the user."""

    class FakeBlogPostsService:
        async def get_post(self, post_id: int, *, user_id: str):
            assert post_id == 999
            assert user_id == user_payload["user_id"]
            return None

    apply_overrides(
        {
            get_tenant_config: lambda: tenant_config,
            get_blog_posts_service: lambda: FakeBlogPostsService(),
            get_user_data: lambda: user_payload,
        }
    )

    response = client.get("/v1/blog-posts/999", headers={"X-Tenant-ID": "tenant_1"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Blog Post not found"}


def test_update_blog_post_returns_updated_resource(
    client,
    apply_overrides,
    tenant_config,
    user_payload,
) -> None:
    """Update an existing blog post and return the updated response body."""
    existing = _blog_post(post_id=5, title="Old title", content="Old body")
    updated = _blog_post(post_id=5, title="New title", content="New body")

    class FakeBlogPostsService:
        async def get_post(self, post_id: int, *, user_id: str):
            assert post_id == 5
            assert user_id == user_payload["user_id"]
            return existing

        async def update_post(self, post, payload):
            assert post is existing
            assert payload.title == "New title"
            assert payload.content == "New body"
            return updated

    apply_overrides(
        {
            get_tenant_config: lambda: tenant_config,
            get_blog_posts_service: lambda: FakeBlogPostsService(),
            get_user_data: lambda: user_payload,
        }
    )

    response = client.patch(
        "/v1/blog-posts/5",
        json={"title": "New title", "content": "New body"},
        headers={"X-Tenant-ID": "tenant_1"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "New title"


def test_delete_blog_post_returns_no_content(
    client,
    apply_overrides,
    tenant_config,
    user_payload,
) -> None:
    """Delete an existing blog post and return an empty 204 response."""
    existing = _blog_post(post_id=9)
    calls = {"deleted": False}

    class FakeBlogPostsService:
        async def get_post(self, post_id: int, *, user_id: str):
            assert post_id == 9
            assert user_id == user_payload["user_id"]
            return existing

        async def delete_post(self, post):
            assert post is existing
            calls["deleted"] = True

    apply_overrides(
        {
            get_tenant_config: lambda: tenant_config,
            get_blog_posts_service: lambda: FakeBlogPostsService(),
            get_user_data: lambda: user_payload,
        }
    )

    response = client.delete("/v1/blog-posts/9", headers={"X-Tenant-ID": "tenant_1"})

    assert response.status_code == 204
    assert response.content == b""
    assert calls["deleted"] is True


def test_blog_posts_require_active_tenant(
    client,
    apply_overrides,
    inactive_tenant_config,
    user_payload,
) -> None:
    """Apply active-tenant enforcement to blog post routes as well."""
    apply_overrides(
        {
            get_tenant_config: lambda: inactive_tenant_config,
            get_user_data: lambda: user_payload,
        }
    )

    response = client.get("/v1/blog-posts", headers={"X-Tenant-ID": "tenant_1"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Tenant 'tenant_2' is not active!"}
