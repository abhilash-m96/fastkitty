"""Row-per-tenant strategy tests."""

from types import SimpleNamespace

import pytest

from config.settings import Settings
from db.tenancy_strategy import (
    RowTenancyStrategy,
    TenantContext,
    _apply_row_tenant_scope,
    _stamp_row_tenant_writes,
    get_current_row_tenant_id,
    set_current_row_tenant_id,
)
from models.posts import BlogPost
from schemas.tenancy import DatabaseConfig, TenantConfig, TenantSecrets


class FakeAsyncSession:
    def __init__(self) -> None:
        self.rollback_calls = 0
        self.close_calls = 0
        self.info: dict[str, object] = {}
        self.sync_session = object()

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class FakeAsyncEngine:
    def __init__(self, url: str) -> None:
        self.url = url
        self.dispose_calls = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1


def _make_tenant_context(
    tenant_id: str,
    *,
    database_uri: str = "postgresql://shared-db/app",
) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_config=TenantConfig(
            tenant_id=tenant_id,
            display_name=f"Tenant {tenant_id}",
            is_active=True,
        ),
        tenant_secrets=TenantSecrets(
            tenant_id=tenant_id,
            database_config=DatabaseConfig(
                host="localhost",
                port=5432,
                username="user",
                password="password",
                database_name="shared_db",
                database_uri=database_uri,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_row_strategy_reuses_shared_engine_and_resets_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_engines: list[FakeAsyncEngine] = []
    registered_events: list[str] = []

    def fake_create_async_engine(url: str, **_: object) -> FakeAsyncEngine:
        engine = FakeAsyncEngine(url)
        created_engines.append(engine)
        return engine

    def fake_async_sessionmaker(**_: object):
        def _factory() -> FakeAsyncSession:
            return FakeAsyncSession()

        return _factory

    def fake_listen(_: object, event_name: str, __: object) -> None:
        registered_events.append(event_name)

    monkeypatch.setattr("db.tenancy_strategy.create_async_engine", fake_create_async_engine)
    monkeypatch.setattr("db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker)
    monkeypatch.setattr("db.tenancy_strategy.event.listen", fake_listen)

    strategy = RowTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="row",
            USER_DATA_SOURCE={"type": "header"},
        )
    )
    tenant_one = _make_tenant_context("tenant_1")
    tenant_two = _make_tenant_context("tenant_2")

    generator_one = strategy.get_session(tenant_one)
    session_one = await anext(generator_one)
    assert session_one.info["tenant_id"] == "tenant_1"
    assert get_current_row_tenant_id() == "tenant_1"

    generator_two = strategy.get_session(tenant_two)
    session_two = await anext(generator_two)
    assert session_two.info["tenant_id"] == "tenant_2"
    assert len(created_engines) == 1
    assert registered_events == [
        "do_orm_execute",
        "before_flush",
        "do_orm_execute",
        "before_flush",
    ]

    await generator_two.aclose()
    await generator_one.aclose()

    with pytest.raises(RuntimeError, match="Row strategy requires a tenant context"):
        get_current_row_tenant_id()

    await strategy.teardown()


def test_row_strategy_requires_tenant_context_for_reads() -> None:
    execute_state = SimpleNamespace(
        is_select=True,
        is_column_load=False,
        is_relationship_load=False,
        statement=SimpleNamespace(options=lambda *args: args),
    )

    with pytest.raises(RuntimeError, match="Row strategy requires a tenant context"):
        _apply_row_tenant_scope(execute_state)


def test_row_strategy_applies_tenant_scope_to_selects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_token = set_current_row_tenant_id("tenant_1")
    captured: dict[str, object] = {}

    def fake_with_loader_criteria(model: object, criteria: object, **kwargs: object) -> str:
        captured["model"] = model
        captured["criteria"] = criteria
        captured["kwargs"] = kwargs
        return "tenant-criteria"

    class FakeStatement:
        def options(self, option: object) -> str:
            captured["option"] = option
            return "scoped-statement"

    monkeypatch.setattr("db.tenancy_strategy.with_loader_criteria", fake_with_loader_criteria)
    execute_state = SimpleNamespace(
        is_select=True,
        is_column_load=False,
        is_relationship_load=False,
        statement=FakeStatement(),
    )

    _apply_row_tenant_scope(execute_state)

    assert execute_state.statement == "scoped-statement"
    assert captured["option"] == "tenant-criteria"
    assert captured["kwargs"] == {"include_aliases": True}

    from db.tenancy_strategy import reset_current_row_tenant_id

    reset_current_row_tenant_id(tenant_token)


def test_row_strategy_stamps_new_instances_with_tenant_id() -> None:
    tenant_token = set_current_row_tenant_id("tenant_1")
    post = BlogPost(title="Title", content="Body", author="Author")
    sync_session = SimpleNamespace(new=[post], dirty=[])

    _stamp_row_tenant_writes(sync_session)

    assert post.tenant_id == "tenant_1"

    from db.tenancy_strategy import reset_current_row_tenant_id

    reset_current_row_tenant_id(tenant_token)


def test_row_strategy_rejects_cross_tenant_writes() -> None:
    tenant_token = set_current_row_tenant_id("tenant_1")
    post = BlogPost(title="Title", content="Body", author="Author")
    post.tenant_id = "tenant_2"
    sync_session = SimpleNamespace(new=[], dirty=[post])

    with pytest.raises(
        ValueError, match="Row strategy detected a cross-tenant write for BlogPost"
    ):
        _stamp_row_tenant_writes(sync_session)

    from db.tenancy_strategy import reset_current_row_tenant_id

    reset_current_row_tenant_id(tenant_token)
