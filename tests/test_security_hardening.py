"""Security hardening and tenancy isolation regression tests."""

import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from api.deps.db import get_db
from api.deps.tenancy import get_feature_config, get_tenant_secrets
from config.settings import Settings
from db.tenancy_strategy import (
    DatabaseTenancyStrategy,
    RowTenancyStrategy,
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

    # Patch create_async_engine and async_sessionmaker to avoid real DB connections
    fake_engine = MagicMock()
    fake_sessionmaker = MagicMock()

    original_engines = strategy._engines
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
        response = client.get(
            "/feature-route", headers={"X-Tenant-ID": "inactive_co"}
        )
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

from sqlalchemy import Integer, String, create_engine, event as sa_event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from models.base import TenantScopedModel


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
