"""Security hardening and tenancy isolation regression tests."""

import json
import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import (
    Integer,
    String,
    create_engine,
    delete,
    event as sa_event,
    select,
    update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from api.deps.db import get_db
from api.deps.tenancy import get_feature_config, get_tenant_id
from api.deps.user_data import _extract_jwt_token, _extract_single_header_claims
from config.settings import (
    Settings,
    UserDataHeaderSource,
    UserDataJWTSource,
    UserDataSingleHeaderClaimsSource,
    get_settings,
)
from db.tenancy_strategy import (
    DatabaseTenancyStrategy,
    SchemaTenancyStrategy,
    TenantDBContext,
    _ExecuteState,
    _SyncSessionLike,
    _apply_row_tenant_scope,
    _mask_url,
    _stamp_row_tenant_writes,
    set_current_row_tenant_id,
    reset_current_row_tenant_id,
)
from main import lifespan
from models.base import TenantScopedModel
from models.posts import BlogPost
from schemas.tenancy import DatabaseConfig, FeatureConfig, TenantConfig, TenantSecrets


# ---------------------------------------------------------------------------
# Blocker 1 & 2: URL Password Masking in Logs and Exceptions
# ---------------------------------------------------------------------------


def test_mask_url_masks_password() -> None:
    uri = "postgresql+asyncpg://app_user:SuperSecretPw123@localhost:5432/my_tenant_db"
    masked = _mask_url(uri)
    assert "SuperSecretPw123" not in masked
    assert "app_user:***@localhost:5432" in masked


def test_mask_url_safe_for_clean_urls() -> None:
    uri = "postgresql+asyncpg://app_user@localhost:5432/my_tenant_db"
    assert _mask_url(uri) == uri
    sqlite_uri = "sqlite+aiosqlite:///:memory:"
    assert "password" not in _mask_url(sqlite_uri)


def test_mask_url_fallback_for_non_standard_schemes() -> None:
    uri = "customproto://admin:TopSecret@cluster-node:9000/db"
    masked = _mask_url(uri)
    assert "TopSecret" not in masked
    assert "admin:***@" in masked


@pytest.mark.asyncio
async def test_database_strategy_masks_password_in_pool_conflict_error() -> None:
    secret_pw = "SuperSecretDbPassword!"
    uri = f"postgresql+asyncpg://user:{secret_pw}@localhost:5432/db"

    strategy = DatabaseTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="database",
            USER_DATA_SOURCE={"type": "header"},
        )
    )

    tenant_1 = TenantDBContext(
        tenant_id="tenant_1",
        db_config=DatabaseConfig(
            host="localhost",
            port=5432,
            username="user",
            password=secret_pw,
            database_name="db",
            database_uri=uri,
            pool_size=5,
        ),
    )
    tenant_2 = TenantDBContext(
        tenant_id="tenant_2",
        db_config=DatabaseConfig(
            host="localhost",
            port=5432,
            username="user",
            password=secret_pw,
            database_name="db",
            database_uri=uri,
            pool_size=15,  # Conflicting pool size
        ),
    )

    entry = strategy._create_entry(db_uri=uri, db_config=tenant_1.db_config)
    strategy._engines[uri] = entry

    with pytest.raises(ValueError) as exc_info:
        await strategy._acquire_entry(tenant_2.db_config)

    error_msg = str(exc_info.value)
    assert secret_pw not in error_msg
    assert "user:***@localhost:5432" in error_msg

    await strategy.teardown()


@pytest.mark.asyncio
async def test_shared_strategy_masks_password_in_conflicting_url_error() -> None:
    secret_pw_1 = "Secret1!"
    secret_pw_2 = "Secret2!"
    uri_1 = f"postgresql+asyncpg://user:{secret_pw_1}@localhost:5432/db1"
    uri_2 = f"postgresql+asyncpg://user:{secret_pw_2}@localhost:5432/db2"

    strategy = SchemaTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="schema",
            USER_DATA_SOURCE={"type": "header"},
        )
    )

    tenant_1 = TenantDBContext(
        tenant_id="tenant_1",
        db_config=DatabaseConfig(
            host="localhost",
            port=5432,
            username="user",
            password=secret_pw_1,
            database_name="db1",
            database_uri=uri_1,
            schema_name="tenant_one",
        ),
    )
    tenant_2 = TenantDBContext(
        tenant_id="tenant_2",
        db_config=DatabaseConfig(
            host="localhost",
            port=5432,
            username="user",
            password=secret_pw_2,
            database_name="db2",
            database_uri=uri_2,
            schema_name="tenant_two",
        ),
    )

    # Prime shared entry with uri_1
    strategy._shared_entry = strategy._create_entry(
        db_uri=uri_1, db_config=tenant_1.db_config
    )

    with pytest.raises(ValueError) as exc_info:
        await strategy._get_or_create_entry(tenant_2.db_config, strategy_name="Schema")

    error_msg = str(exc_info.value)
    assert secret_pw_2 not in error_msg
    assert "user:***@localhost:5432/db2" in error_msg

    await strategy.teardown()


@pytest.mark.asyncio
async def test_database_strategy_masks_password_in_allocation_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_pw = "SuperSecretLogPass!"
    uri = f"postgresql+asyncpg://user:{secret_pw}@localhost:5432/db"

    strategy = DatabaseTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="database",
            USER_DATA_SOURCE={"type": "header"},
        )
    )

    db_config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="user",
        password=secret_pw,
        database_name="db",
        database_uri=uri,
    )

    with caplog.at_level(logging.INFO):
        entry = await strategy._acquire_entry(db_config)
        await strategy._release_entry(entry)

    assert secret_pw not in caplog.text
    assert "user:***@localhost:5432" in caplog.text

    await strategy.teardown()


# ---------------------------------------------------------------------------
# Blocker 3: Inactive Tenant Guard is Fail-Closed (Not Opt-In)
# ---------------------------------------------------------------------------


def test_get_db_rejects_inactive_tenant_without_router_dependency() -> None:
    """A route depending ONLY on get_db must reject inactive tenants before opening a DB session."""
    app = FastAPI()

    # Create dummy tenant configs: active and inactive
    configs = {
        "active_co": TenantConfig(
            tenant_id="active_co",
            display_name="Active Co",
            is_active=True,
            features={},
        ),
        "inactive_co": TenantConfig(
            tenant_id="inactive_co",
            display_name="Inactive Co",
            is_active=False,
            features={},
        ),
    }
    secrets = {
        "active_co": TenantSecrets(
            tenant_id="active_co",
            database_config=DatabaseConfig(
                host="localhost",
                port=5432,
                username="u",
                password="p",
                database_name="db",
            ),
        ),
        "inactive_co": TenantSecrets(
            tenant_id="inactive_co",
            database_config=DatabaseConfig(
                host="localhost",
                port=5432,
                username="u",
                password="p",
                database_name="db",
            ),
        ),
    }

    class FakeConfigService:
        def get_tenant_config(self, tenant_id: str) -> TenantConfig | None:
            return configs.get(tenant_id)

    class FakeSecretsService:
        def get_tenant_secrets(self, tenant_id: str) -> TenantSecrets | None:
            return secrets.get(tenant_id)

    from api.deps.tenancy import get_tenancy_config_service, get_tenancy_secrets_service
    import api.deps.db as db_module

    strategy_invoked = {"count": 0}

    def fake_get_strategy(_: FastAPI):
        strategy_invoked["count"] += 1
        fake_strat = MagicMock()
        return fake_strat

    app.dependency_overrides[get_tenancy_config_service] = lambda: FakeConfigService()
    app.dependency_overrides[get_tenancy_secrets_service] = lambda: FakeSecretsService()

    original_get_strategy = db_module.get_app_tenancy_strategy
    db_module.get_app_tenancy_strategy = fake_get_strategy

    # Define route with ONLY get_db — NO require_active_tenant in router
    @app.get("/bare-db-route")
    async def bare_db_route(db: Any = Depends(get_db)):
        return {"status": "ok"}

    try:
        with TestClient(app) as client:
            # Inactive tenant must receive 403 Forbidden
            response_inactive = client.get(
                "/bare-db-route", headers={"X-Tenant-ID": "inactive_co"}
            )
            assert response_inactive.status_code == 403
            assert "is not active" in response_inactive.json()["detail"]
            assert strategy_invoked["count"] == 0  # No DB session ever resolved!

            # Missing/Unknown tenant must receive 404 Not Found
            response_unknown = client.get(
                "/bare-db-route", headers={"X-Tenant-ID": "non_existent"}
            )
            assert response_unknown.status_code == 404
            assert strategy_invoked["count"] == 0

            # Missing header must receive 422/400
            response_no_header = client.get("/bare-db-route")
            assert response_no_header.status_code in (400, 422)
            assert strategy_invoked["count"] == 0
    finally:
        db_module.get_app_tenancy_strategy = original_get_strategy


def test_get_feature_config_rejects_inactive_tenant() -> None:
    """get_feature_config must reject inactive tenants with 403."""
    app = FastAPI()

    configs = {
        "inactive_co": TenantConfig(
            tenant_id="inactive_co",
            display_name="Inactive Co",
            is_active=False,
            features={"custom_feature": FeatureConfig()},
        ),
    }

    class FakeConfigService:
        def get_tenant_config(self, tenant_id: str) -> TenantConfig | None:
            return configs.get(tenant_id)

    from api.deps.tenancy import get_tenancy_config_service

    app.dependency_overrides[get_tenancy_config_service] = lambda: FakeConfigService()

    @app.get("/feature-route", name="custom_feature")
    async def feature_route(
        feature: FeatureConfig | None = Depends(get_feature_config("custom_feature")),
    ):
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/feature-route", headers={"X-Tenant-ID": "inactive_co"})
        assert response.status_code == 403
        assert "is not active" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Blocker 4: Row Strategy ORM Bulk Update & Delete Scoping
# ---------------------------------------------------------------------------


def test_row_strategy_scopes_orm_bulk_update_statement() -> None:
    """Verifies update(Model) is scoped with WHERE tenant_id = current_tenant."""
    tenant_token = set_current_row_tenant_id("tenant_target")

    stmt = update(BlogPost).values(title="Hacked Title")
    execute_state = cast(
        _ExecuteState,
        SimpleNamespace(
            is_select=False,
            is_update=True,
            is_delete=False,
            is_column_load=False,
            is_relationship_load=False,
            statement=stmt,
        ),
    )

    _apply_row_tenant_scope(execute_state)

    compiled = str(execute_state.statement.compile())
    assert "WHERE blog_posts.tenant_id = :tenant_id_1" in compiled

    reset_current_row_tenant_id(tenant_token)


def test_row_strategy_scopes_orm_bulk_delete_statement() -> None:
    """Verifies delete(Model) is scoped with WHERE tenant_id = current_tenant."""
    tenant_token = set_current_row_tenant_id("tenant_target")

    stmt = delete(BlogPost)
    execute_state = cast(
        _ExecuteState,
        SimpleNamespace(
            is_select=False,
            is_update=False,
            is_delete=True,
            is_column_load=False,
            is_relationship_load=False,
            statement=stmt,
        ),
    )

    _apply_row_tenant_scope(execute_state)

    compiled = str(execute_state.statement.compile())
    assert "WHERE blog_posts.tenant_id = :tenant_id_1" in compiled

    reset_current_row_tenant_id(tenant_token)


def test_row_strategy_rejects_deleting_cross_tenant_instance() -> None:
    """Verifies session.deleted check catches cross-tenant model deletion."""
    tenant_token = set_current_row_tenant_id("tenant_target")

    # Instance belongs to another tenant
    alien_post = BlogPost(title="Post", content="Content", author="Author")
    alien_post.tenant_id = "alien_tenant"

    sync_session = cast(
        _SyncSessionLike,
        SimpleNamespace(new=[], dirty=[], deleted=[alien_post]),
    )

    with pytest.raises(
        ValueError, match="Row strategy detected a cross-tenant delete for BlogPost"
    ):
        _stamp_row_tenant_writes(sync_session)

    reset_current_row_tenant_id(tenant_token)


# ---------------------------------------------------------------------------
# Blocker 2 (End-to-End): Live SQLite Test for Bulk Update & Delete
# ---------------------------------------------------------------------------


class _E2ETestBase(DeclarativeBase):
    pass


class _E2EItem(TenantScopedModel, _E2ETestBase):
    __tablename__ = "security_test_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


def test_row_strategy_e2e_bulk_update_and_delete_isolation_with_sqlite() -> None:
    """Verifies with live SQLite engine that bulk update and delete statements
    cannot affect or delete other tenants' rows under any circumstance.
    """
    engine = create_engine("sqlite:///:memory:")
    _E2ETestBase.metadata.create_all(engine)

    session = Session(engine)
    sa_event.listen(session, "do_orm_execute", _apply_row_tenant_scope)
    sa_event.listen(session, "before_flush", _stamp_row_tenant_writes)

    # Tenant A writes two items
    t_a = set_current_row_tenant_id("tenant_a")
    item_a1 = _E2EItem(name="Item A1")
    item_a2 = _E2EItem(name="Item A2")
    session.add_all([item_a1, item_a2])
    session.commit()
    reset_current_row_tenant_id(t_a)

    # Tenant B writes two items
    t_b = set_current_row_tenant_id("tenant_b")
    item_b1 = _E2EItem(name="Item B1")
    item_b2 = _E2EItem(name="Item B2")
    session.add_all([item_b1, item_b2])
    session.commit()

    # Step 1: Bulk UPDATE under Tenant B
    session.execute(update(_E2EItem).values(name="B Mutated"))
    session.commit()

    # Verify Tenant B sees its updated items
    b_items = session.scalars(select(_E2EItem)).all()
    assert len(b_items) == 2
    assert all(i.name == "B Mutated" for i in b_items)
    reset_current_row_tenant_id(t_b)

    # Verify Tenant A's items are completely untouched
    t_a = set_current_row_tenant_id("tenant_a")
    a_items = session.scalars(select(_E2EItem)).all()
    assert len(a_items) == 2
    assert {i.name for i in a_items} == {"Item A1", "Item A2"}
    reset_current_row_tenant_id(t_a)

    # Step 2: Bulk DELETE under Tenant B
    t_b = set_current_row_tenant_id("tenant_b")
    session.execute(delete(_E2EItem))
    session.commit()

    # Verify Tenant B has 0 items remaining
    b_items_after = session.scalars(select(_E2EItem)).all()
    assert len(b_items_after) == 0
    reset_current_row_tenant_id(t_b)

    # Verify Tenant A STILL has both items intact in the database
    t_a = set_current_row_tenant_id("tenant_a")
    a_items_after = session.scalars(select(_E2EItem)).all()
    assert len(a_items_after) == 2
    assert {i.name for i in a_items_after} == {"Item A1", "Item A2"}

    # Step 3: Attempting cross-tenant delete of loaded instance fails before flush
    alien_item = a_items_after[0]
    reset_current_row_tenant_id(t_a)

    t_b = set_current_row_tenant_id("tenant_b")
    session.delete(alien_item)
    with pytest.raises(
        ValueError, match="Row strategy detected a cross-tenant delete for _E2EItem"
    ):
        session.flush()

    reset_current_row_tenant_id(t_b)
    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# Blocker 1 & 3: Masking on Engine Disposal Warnings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_strategy_masks_password_in_disposal_timeout_warning(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that engine disposal timeout warnings mask credentials."""
    import asyncio
    from db.tenancy_strategy import _DatabaseEngineEntry

    secret_pw = "SuperDisposalSecretPass!"
    uri = f"postgresql+asyncpg://admin:{secret_pw}@db-cluster:5432/production_db"

    strategy = DatabaseTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="database",
            USER_DATA_SOURCE={"type": "header"},
        )
    )

    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()

    entry = _DatabaseEngineEntry(
        engine=fake_engine,
        session_factory=MagicMock(),
        pool_config={"pool_size": 5, "max_overflow": 10, "pool_timeout": 30.0},
        db_uri=uri,
        active_sessions=1,  # Simulate busy session
        idle_event=asyncio.Event(),
    )

    monkeypatch.setattr("db.tenancy_strategy._DISPOSE_IDLE_TIMEOUT", 0.01)

    with caplog.at_level(logging.WARNING):
        await strategy._dispose_entry(entry)

    assert secret_pw not in caplog.text
    assert "admin:***@db-cluster:5432/production_db" in caplog.text
    assert fake_engine.dispose.await_count == 1


# ---------------------------------------------------------------------------
# Tenant ID Header Validation & Anti-Smuggling Tests
# ---------------------------------------------------------------------------


def test_duplicate_tenant_id_headers_rejected() -> None:
    """Duplicate X-Tenant-ID headers must be rejected with 400 Bad Request to prevent smuggling."""
    test_app = FastAPI()

    @test_app.get("/test-tenant-id")
    def _route(tenant_id: str = Depends(get_tenant_id)) -> dict[str, str]:
        return {"tenant_id": tenant_id}

    with TestClient(test_app) as client:
        response = client.get(
            "/test-tenant-id",
            headers=[("X-Tenant-ID", "tenant_a"), ("X-Tenant-ID", "tenant_b")],
        )
        assert response.status_code == 400
        assert "Duplicate X-Tenant-ID headers detected" in response.json()["detail"]


@pytest.mark.parametrize(
    "invalid_tenant_id",
    [
        "../vault/secret",
        "tenant;drop table",
        "tenant/sub",
        "tenant with space",
        "tenant$evil",
        "tenant\nnewline",
        "a" * 64,  # Exceeds max length of 63 chars
        "",
        "   ",
    ],
)
def test_invalid_tenant_id_rejected_by_get_tenant_id(invalid_tenant_id: str) -> None:
    """Invalid tenant IDs (path traversal, SQL injection, illegal chars, too long) must return 400."""
    test_app = FastAPI()

    @test_app.get("/test-tenant-id")
    def _route(tenant_id: str = Depends(get_tenant_id)) -> dict[str, str]:
        return {"tenant_id": tenant_id}

    with TestClient(test_app) as client:
        response = client.get(
            "/test-tenant-id",
            headers={"X-Tenant-ID": invalid_tenant_id},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "Invalid Tenant ID format" in detail or "Tenant ID is required" in detail


def test_valid_tenant_id_accepted_and_normalized() -> None:
    """Valid tenant IDs must be accepted and normalized to lowercase."""
    test_app = FastAPI()

    @test_app.get("/test-tenant-id")
    def _route(tenant_id: str = Depends(get_tenant_id)) -> dict[str, str]:
        return {"tenant_id": tenant_id}

    with TestClient(test_app) as client:
        response = client.get(
            "/test-tenant-id",
            headers={"X-Tenant-ID": "Tenant_Alpha-01"},
        )
        assert response.status_code == 200
        assert response.json()["tenant_id"] == "tenant_alpha-01"


# ---------------------------------------------------------------------------
# Provider Defense-in-Depth Tenant ID Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "invalid_id",
    [
        "../traversal",
        "..",
        "/etc/passwd",
        "tenant/path",
        "tenant;drop",
        "A" * 64,
        "",
    ],
)
def test_validate_tenant_id_helper_rejects_malformed(invalid_id: str) -> None:
    """Provider-level validation helper must raise ValueError on malformed tenant IDs."""
    from config.tenancy_providers import validate_tenant_id

    with pytest.raises(ValueError, match="Invalid tenant_id"):
        validate_tenant_id(invalid_id)


def test_validate_tenant_id_helper_accepts_valid() -> None:
    """Provider-level validation helper accepts valid normalized tenant IDs."""
    from config.tenancy_providers import validate_tenant_id

    assert validate_tenant_id("tenant_1") == "tenant_1"
    assert validate_tenant_id("tenant-alpha-02") == "tenant-alpha-02"
    assert validate_tenant_id("acme_corp_42") == "acme_corp_42"


# ---------------------------------------------------------------------------
# Public Health Check Route
# ---------------------------------------------------------------------------


def test_public_health_endpoint_accessible_without_auth_or_tenant() -> None:
    """GET /v1/health must be publicly accessible without X-Tenant-ID or auth tokens."""
    from main import app

    with TestClient(app) as client:
        response = client.get("/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Upstream Auth Hardening (JWT alg: none and Cross-Tenant Claim Mismatch)
# ---------------------------------------------------------------------------


def test_jwt_mode_rejects_alg_none() -> None:
    """JWT tokens specifying alg='none' must be rejected with 401 Unauthorized."""
    import base64
    import json

    header_b64 = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    payload_b64 = (
        base64.urlsafe_b64encode(
            json.dumps({"sub": "attacker", "tenant_id": "tenant_1"}).encode()
        )
        .decode()
        .rstrip("=")
    )
    token = f"{header_b64}.{payload_b64}."

    source = UserDataJWTSource()

    with pytest.raises(ValueError, match="JWT 'none' algorithm is forbidden"):
        _extract_jwt_token(source, token)


def test_jwt_mode_rejects_cross_tenant_token_claim() -> None:
    """JWT tokens containing a tenant claim mismatching requested X-Tenant-ID must be rejected."""
    import jwt

    token = jwt.encode(
        {"sub": "user_a", "tenant_id": "tenant_a"},
        key="test-secret-key-that-is-at-least-32-bytes-long",
        algorithm="HS256",
    )
    source = UserDataJWTSource()

    # Matching tenant passes
    user = _extract_jwt_token(source, token, expected_tenant_id="tenant_a")
    assert user.user_id == "user_a"

    # Mismatched tenant raises PermissionError
    with pytest.raises(
        PermissionError,
        match="Token tenant 'tenant_a' does not match requested tenant 'tenant_b'",
    ):
        _extract_jwt_token(source, token, expected_tenant_id="tenant_b")


def test_claims_header_mode_rejects_cross_tenant_claim() -> None:
    """Single header claims containing a tenant mismatching requested X-Tenant-ID must be rejected."""
    source = UserDataSingleHeaderClaimsSource()
    claims_json = '{"id": "user_1", "tenant_id": "tenant_a"}'

    # Matching tenant passes
    user = _extract_single_header_claims(
        source, claims_json, expected_tenant_id="tenant_a"
    )
    assert user.user_id == "user_1"

    # Mismatched tenant raises PermissionError
    with pytest.raises(
        PermissionError,
        match="Claims tenant 'tenant_a' does not match requested tenant 'tenant_b'",
    ):
        _extract_single_header_claims(
            source, claims_json, expected_tenant_id="tenant_b"
        )


# ---------------------------------------------------------------------------
# Lifespan Upstream Auth Gate in Non-Dev Environments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_enforces_trust_upstream_auth_in_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifespan must refuse to start in production if USER_DATA_SOURCE is set and TRUST_UPSTREAM_AUTH is False."""
    test_settings = get_settings().model_copy(
        update={
            "ENV": "prod",
            "USER_DATA_SOURCE": UserDataHeaderSource(),
            "TRUST_UPSTREAM_AUTH": False,
        }
    )
    monkeypatch.setattr("main.settings", test_settings)

    dummy_app = FastAPI()
    with pytest.raises(RuntimeError, match="TRUST_UPSTREAM_AUTH must be set to True"):
        async with lifespan(dummy_app):
            pass


# ---------------------------------------------------------------------------
# Special Characters in DB Passwords & Config Repr Masking
# ---------------------------------------------------------------------------


def test_special_characters_in_password_url_encoded() -> None:
    """Special characters in database passwords (@, /, :, #) must be safely encoded in URI."""
    from schemas.tenancy import DatabaseConfig
    from sqlalchemy.engine import make_url

    complex_password = "p@ss/w:rd#1?query=yes&pct=100%"
    db_config = DatabaseConfig(
        host="db.internal",
        port=5432,
        username="tenant:admin@corp",
        password=complex_password,
        database_name="app_db",
    )

    url = make_url(db_config.database_uri)
    assert url.host == "db.internal"
    assert url.port == 5432
    assert url.username == "tenant:admin@corp"
    assert url.password == complex_password
    assert url.database == "app_db"


def test_database_config_repr_and_str_mask_password() -> None:
    """DatabaseConfig __repr__ and __str__ must never leak the plaintext password or unmasked URI."""
    from schemas.tenancy import DatabaseConfig

    secret_pw = "super_secret_password_123"
    db_config = DatabaseConfig(
        host="db.internal",
        port=5432,
        username="app_user",
        password=secret_pw,
        database_name="app_db",
    )

    repr_str = repr(db_config)
    str_str = str(db_config)

    assert secret_pw not in repr_str
    assert secret_pw not in str_str
    assert "password='***'" in repr_str
    assert "app_user:***@db.internal" in repr_str


# ---------------------------------------------------------------------------
# Require Tenant Claim Setting in JWT & Claims Sources
# ---------------------------------------------------------------------------


def test_jwt_mode_rejects_missing_tenant_claim_when_required() -> None:
    """When require_tenant_claim=True, JWT without tenant claim must be rejected."""
    source = UserDataJWTSource(require_tenant_claim=True)
    token = jwt.encode({"sub": "user_1"}, "secret", algorithm="HS256")

    with pytest.raises(
        PermissionError,
        match="Token is missing required tenant claim matching requested tenant 'tenant_a'",
    ):
        _extract_jwt_token(source, token, expected_tenant_id="tenant_a")


def test_jwt_mode_supports_custom_tenant_id_claim() -> None:
    """Custom tenant_id_claim (e.g. 'org_id') must be used to validate tenant identity."""
    source = UserDataJWTSource(tenant_id_claim="org_id", require_tenant_claim=True)

    # 1. Matching claim succeeds
    token_valid = jwt.encode(
        {"sub": "user_1", "org_id": "tenant_a"}, "secret", algorithm="HS256"
    )
    user = _extract_jwt_token(source, token_valid, expected_tenant_id="tenant_a")
    assert user.user_id == "user_1"

    # 2. Mismatched claim raises PermissionError
    token_mismatch = jwt.encode(
        {"sub": "user_1", "org_id": "tenant_b"}, "secret", algorithm="HS256"
    )
    with pytest.raises(
        PermissionError,
        match="Token tenant 'tenant_b' does not match requested tenant 'tenant_a'",
    ):
        _extract_jwt_token(source, token_mismatch, expected_tenant_id="tenant_a")

    # 3. Missing custom claim raises PermissionError referencing the custom claim name
    token_missing = jwt.encode({"sub": "user_1"}, "secret", algorithm="HS256")
    with pytest.raises(
        PermissionError,
        match="Token is missing required 'org_id' matching requested tenant 'tenant_a'",
    ):
        _extract_jwt_token(source, token_missing, expected_tenant_id="tenant_a")


def test_claims_mode_rejects_missing_tenant_claim_when_required() -> None:
    """When require_tenant_claim=True, claims header without tenant claim must be rejected."""
    source = UserDataSingleHeaderClaimsSource(require_tenant_claim=True)
    claims_json = '{"id": "user_1"}'

    with pytest.raises(
        PermissionError,
        match="Claims header is missing required tenant claim matching requested tenant 'tenant_a'",
    ):
        _extract_single_header_claims(
            source, claims_json, expected_tenant_id="tenant_a"
        )


def test_claims_mode_supports_custom_tenant_id_field() -> None:
    """Custom tenant_id_field (e.g. 'organization') must be used to validate tenant identity."""
    source = UserDataSingleHeaderClaimsSource(
        tenant_id_field="organization", require_tenant_claim=True
    )

    # 1. Matching field succeeds
    claims_valid = json.dumps({"id": "user_1", "organization": "tenant_a"})
    user = _extract_single_header_claims(
        source, claims_valid, expected_tenant_id="tenant_a"
    )
    assert user.user_id == "user_1"

    # 2. Mismatched field raises PermissionError
    claims_mismatch = json.dumps({"id": "user_1", "organization": "tenant_b"})
    with pytest.raises(
        PermissionError,
        match="Claims tenant 'tenant_b' does not match requested tenant 'tenant_a'",
    ):
        _extract_single_header_claims(
            source, claims_mismatch, expected_tenant_id="tenant_a"
        )

    # 3. Missing custom field raises PermissionError referencing the custom field name
    claims_missing = json.dumps({"id": "user_1"})
    with pytest.raises(
        PermissionError,
        match="Claims header is missing required 'organization' matching requested tenant 'tenant_a'",
    ):
        _extract_single_header_claims(
            source, claims_missing, expected_tenant_id="tenant_a"
        )


def test_jwt_and_claims_mode_support_nested_dot_notation_paths() -> None:
    """Extract tenant and user claims from nested objects using dot notation (e.g. 'app_metadata.tenant_id')."""
    jwt_source = UserDataJWTSource(
        tenant_id_claim="app_metadata.tenant_id",
        user_id_claim="user.id",
        user_email_claim="user.email",
        require_tenant_claim=True,
    )
    token = jwt.encode(
        {
            "user": {"id": "nested_user", "email": "nested@example.com"},
            "app_metadata": {"tenant_id": "tenant_nested"},
        },
        "secret",
        algorithm="HS256",
    )
    user_from_jwt = _extract_jwt_token(
        jwt_source, token, expected_tenant_id="tenant_nested"
    )
    assert user_from_jwt.user_id == "nested_user"
    assert user_from_jwt.email == "nested@example.com"

    # Claims mode with nested payload
    claims_source = UserDataSingleHeaderClaimsSource(
        tenant_id_field="metadata.org.id",
        user_id_field="account.uid",
        require_tenant_claim=True,
    )
    claims_payload = json.dumps(
        {
            "account": {"uid": "claims_nested_user"},
            "metadata": {"org": {"id": "tenant_nested"}},
        }
    )
    user_from_claims = _extract_single_header_claims(
        claims_source, claims_payload, expected_tenant_id="tenant_nested"
    )
    assert user_from_claims.user_id == "claims_nested_user"


# ---------------------------------------------------------------------------
# Helpful Startup Failure When Tenant Missing from Secrets
# ---------------------------------------------------------------------------


def test_startup_validation_fails_helpfully_when_tenant_missing_from_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tenant configured in config provider but missing from secrets provider must fail fast with a helpful error."""
    from config.tenancy_strategy_validation import validate_tenancy_strategy_startup
    from schemas.tenancy import TenantMetadata

    class FakeConfigProvider:
        def get_tenants(self) -> list[TenantMetadata]:
            return [
                TenantMetadata(
                    tenant_id="ghost_tenant", display_name="Ghost", is_active=True
                )
            ]

    class FakeSecretsProvider:
        def get_secrets(self, tenant_id: str) -> None:
            return None

    monkeypatch.setattr(
        "config.tenancy_strategy_validation.TenancyConfigProviderFactory.create",
        lambda _: FakeConfigProvider(),
    )
    monkeypatch.setattr(
        "config.tenancy_strategy_validation.TenancySecretsProviderFactory.create",
        lambda _: FakeSecretsProvider(),
    )

    with pytest.raises(
        ValueError,
        match="Tenant 'ghost_tenant' is configured in tenancy config but has no matching secrets entry",
    ):
        validate_tenancy_strategy_startup(get_settings())


# ---------------------------------------------------------------------------
# Startup Warning When REQUIRE_TENANT_CLAIM Disabled in Non-Dev
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_warns_when_require_tenant_claim_disabled_in_prod(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Lifespan should log a warning when REQUIRE_TENANT_CLAIM is False in non-dev with JWT mode."""
    import logging
    from main import lifespan
    from fastapi import FastAPI
    from unittest.mock import AsyncMock

    mock_app = FastAPI()
    jwt_source = UserDataJWTSource(require_tenant_claim=False)

    monkeypatch.setattr("main.settings.ENV", "prod")
    monkeypatch.setattr("main.settings.USER_DATA_SOURCE", jwt_source)
    monkeypatch.setattr("main.settings.TRUST_UPSTREAM_AUTH", True)
    monkeypatch.setattr("main.settings.REQUIRE_TENANT_CLAIM", False)
    monkeypatch.setattr("main.validate_tenancy_strategy_startup", lambda _: None)

    mock_strategy = AsyncMock()
    mock_strategy.setup = AsyncMock()
    mock_strategy.teardown = AsyncMock()
    monkeypatch.setattr("main.create_tenancy_strategy", lambda _: mock_strategy)

    with caplog.at_level(logging.WARNING):
        async with lifespan(mock_app):
            pass

    assert any(
        "REQUIRE_TENANT_CLAIM is disabled in non-dev environment" in record.message
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# Tenant Isolation & Validation Hardening (Review Fixes)
# ---------------------------------------------------------------------------


def test_startup_validation_rejects_duplicate_schema_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup validation in schema mode must reject duplicate schema_names across tenants."""
    from config.tenancy_strategy_validation import validate_tenancy_strategy_startup
    from schemas.tenancy import TenantMetadata

    class FakeConfigProvider:
        def get_tenants(self) -> list[TenantMetadata]:
            return [
                TenantMetadata(
                    tenant_id="tenant_a", display_name="Tenant A", is_active=True
                ),
                TenantMetadata(
                    tenant_id="tenant_b", display_name="Tenant B", is_active=True
                ),
            ]

    class FakeSecretsProvider:
        def get_secrets(self, tenant_id: str) -> TenantSecrets:
            return TenantSecrets(
                tenant_id=tenant_id,
                database_config=DatabaseConfig(
                    host="localhost",
                    port=5432,
                    username="user",
                    password="password",
                    database_name="db",
                    schema_name="shared_schema",
                ),
            )

    settings = get_settings().model_copy(update={"TENANCY_DB_STRATEGY": "schema"})
    monkeypatch.setattr(
        "config.tenancy_strategy_validation.TenancyConfigProviderFactory.create",
        lambda _: FakeConfigProvider(),
    )
    monkeypatch.setattr(
        "config.tenancy_strategy_validation.TenancySecretsProviderFactory.create",
        lambda _: FakeSecretsProvider(),
    )

    with pytest.raises(
        ValueError,
        match="Duplicate schema_name 'shared_schema' detected: used by both 'tenant_a' and 'tenant_b'",
    ):
        validate_tenancy_strategy_startup(settings)


def test_file_providers_reject_mismatched_key_and_inner_tenant_id(tmp_path) -> None:
    """File config & secrets providers must reject entries where JSON key != inner tenant_id."""
    from config.tenancy_providers import (
        FileTenancyConfigProvider,
        FileTenancySecretsProvider,
    )

    bad_config = tmp_path / "bad_config.json"
    bad_config.write_text(
        json.dumps(
            {
                "alice": {
                    "tenant_id": "bob",
                    "display_name": "Alice as Bob",
                    "is_active": True,
                }
            }
        )
    )
    config_provider = FileTenancyConfigProvider(str(bad_config))
    with pytest.raises(
        ValueError,
        match="Tenancy config key 'alice' does not match inner tenant_id 'bob'",
    ):
        config_provider.get_tenants()

    with pytest.raises(
        ValueError,
        match="Tenancy config key 'alice' does not match inner tenant_id 'bob'",
    ):
        config_provider.get_config("alice")

    bad_secrets = tmp_path / "bad_secrets.json"
    bad_secrets.write_text(
        json.dumps(
            {
                "alice": {
                    "tenant_id": "bob",
                    "database_config": {
                        "host": "localhost",
                        "port": 5432,
                        "username": "user",
                        "password": "password",
                        "database_name": "bob_db",
                    },
                }
            }
        )
    )
    secrets_provider = FileTenancySecretsProvider(str(bad_secrets))
    with pytest.raises(
        ValueError,
        match="Tenancy secrets key 'alice' does not match inner tenant_id 'bob'",
    ):
        secrets_provider.get_secrets("alice")


def test_runtime_dependencies_reject_tenant_id_mismatches() -> None:
    """Runtime dependencies must return 500 if resolved config or secrets tenant_id mismatches."""
    from fastapi import HTTPException
    from api.deps.tenancy import get_tenant_config, get_tenant_secrets
    from unittest.mock import Mock

    mock_config_svc = Mock()
    mock_config_svc.get_tenant_config.return_value = TenantConfig(
        tenant_id="bob", display_name="Bob", is_active=True
    )
    with pytest.raises(HTTPException) as exc_info:
        get_tenant_config(tenant_id="alice", tenancy_config_service=mock_config_svc)
    assert exc_info.value.status_code == 500
    assert "Tenant configuration ID mismatch" in exc_info.value.detail

    mock_secrets_svc = Mock()
    mock_secrets_svc.get_tenant_secrets.return_value = TenantSecrets(
        tenant_id="mallory",
        database_config=DatabaseConfig(
            host="localhost",
            port=5432,
            username="user",
            password="password",
            database_name="mallory_db",
        ),
    )
    alice_config = TenantConfig(tenant_id="alice", display_name="Alice", is_active=True)
    with pytest.raises(HTTPException) as exc_info:
        get_tenant_secrets(
            tenant_config=alice_config,
            tenancy_secrets_service=mock_secrets_svc,
        )
    assert exc_info.value.status_code == 500
    assert "Tenant secrets ID mismatch" in exc_info.value.detail


def test_active_tenant_with_missing_secrets_returns_500() -> None:
    """An active tenant whose secrets are missing must result in 500 Internal Server Error."""
    from fastapi import HTTPException
    from api.deps.tenancy import get_tenant_secrets
    from config.tenancy_providers import TenantNotFoundError
    from unittest.mock import Mock

    mock_secrets_svc = Mock()
    mock_secrets_svc.get_tenant_secrets.side_effect = TenantNotFoundError("missing")
    alice_config = TenantConfig(tenant_id="alice", display_name="Alice", is_active=True)

    with pytest.raises(HTTPException) as exc_info:
        get_tenant_secrets(
            tenant_config=alice_config,
            tenancy_secrets_service=mock_secrets_svc,
        )
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Tenant is not correctly configured"
    assert "alice" not in exc_info.value.detail


def test_secret_str_masks_tokens_in_settings_repr() -> None:
    """Vault and Consul tokens must be masked with SecretStr in settings repr."""
    from config.settings import (
        HCConsulTenancyConfigConnection,
        HCVaultTenancySecretsConnection,
    )
    from pydantic import SecretStr

    consul_conn = HCConsulTenancyConfigConnection(
        url="https://consul.example.com",
        token="my-super-secret-consul-token",
        consul_prefix="tenants/config/",
    )
    assert "my-super-secret-consul-token" not in repr(consul_conn)
    assert "**********" in repr(consul_conn)
    assert isinstance(consul_conn.token, SecretStr)

    vault_conn = HCVaultTenancySecretsConnection(
        url="https://vault.example.com",
        token="my-super-secret-vault-token",
        vault_kv_path="secret/data/tenants/{tenant_id}",
    )
    assert "my-super-secret-vault-token" not in repr(vault_conn)
    assert "**********" in repr(vault_conn)
    assert isinstance(vault_conn.token, SecretStr)


def test_blog_post_content_max_length_validation() -> None:
    """BlogPostCreate and BlogPostUpdate must enforce max_length=50,000 on content."""
    from pydantic import ValidationError
    from schemas.posts import BlogPostCreate, BlogPostUpdate

    too_long = "a" * 50_001
    with pytest.raises(ValidationError):
        BlogPostCreate(title="Test", content=too_long)

    with pytest.raises(ValidationError):
        BlogPostUpdate(content=too_long)

    valid = BlogPostCreate(title="Test", content="a" * 50_000)
    assert len(valid.content) == 50_000


def test_hello_route_safe_string_substitution(client: TestClient) -> None:
    """Hello route must use safe substitution and not fail on unmatched braces."""
    response = client.get("/v1/hello", headers={"X-Tenant-ID": "tenant_1"})
    assert response.status_code == 200
    assert "Hello" in response.json()["message"]


# ---------------------------------------------------------------------------
# Mask Secrets in Pydantic Validation Errors
# ---------------------------------------------------------------------------


def test_settings_validation_error_masks_secrets_on_missing_required_field() -> None:
    """Pydantic validation errors for Settings must not leak tokens when fields are missing."""
    from pydantic import ValidationError

    sentinel_token = "hvs.SENTINEL"
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            TENANCY_SECRETS_CONNECTION={
                "type": "hc_vault",
                "token": sentinel_token,
            }
        )

    err = str(exc_info.value)
    assert sentinel_token not in err
    assert "url" in err


def test_settings_validation_error_masks_secrets_on_wrong_discriminator() -> None:
    """Pydantic validation errors for Settings must not leak tokens on invalid discriminator tag."""
    from pydantic import ValidationError

    sentinel_token = "hvs.SENTINEL"
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            TENANCY_SECRETS_CONNECTION={
                "type": "vault",
                "token": sentinel_token,
            }
        )

    err = str(exc_info.value)
    assert sentinel_token not in err
    assert "TENANCY_SECRETS_CONNECTION" in err


def test_tenant_secrets_validation_error_masks_password() -> None:
    """TenantSecrets validation errors must not leak database passwords."""
    from pydantic import ValidationError

    sentinel_password = "SUPER_SECRET_TENANT_DB_PASS"
    with pytest.raises(ValidationError) as exc_info:
        TenantSecrets(
            tenant_id="t1",
            database_config={
                "dialect": "postgresql",
                "host": "localhost",
                "port": "bad_port_not_int",
                "username": "user",
                "password": sentinel_password,
                "database_name": "db",
            },
        )

    err = str(exc_info.value)
    assert sentinel_password not in err
    assert "port" in err

    # Also test invalid database_config dict structure
    with pytest.raises(ValidationError) as exc_info2:
        TenantSecrets.model_validate(
            {
                "tenant_id": "t1",
                "database_config": {"password": sentinel_password},
            }
        )

    err2 = str(exc_info2.value)
    assert sentinel_password not in err2
    assert "host" in err2


def test_database_config_validation_error_masks_password() -> None:
    """DatabaseConfig validation errors must not leak passwords."""
    from pydantic import ValidationError

    sentinel_password = "SUPER_SECRET_DBCONFIG_PASS"
    with pytest.raises(ValidationError) as exc_info:
        DatabaseConfig(
            dialect="postgresql",
            host="localhost",
            port="bad_port_not_int",
            username="user",
            password=sentinel_password,
            database_name="db",
        )

    err = str(exc_info.value)
    assert sentinel_password not in err
    assert "port" in err
