"""Schema-per-tenant strategy tests."""

import asyncio
from typing import Any, cast

import pytest

from config.settings import Settings
from db.tenancy_strategy import SchemaTenancyStrategy, TenantDBContext
from schemas.tenancy import DatabaseConfig


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def exec_driver_sql(self, sql: str) -> None:
        self.statements.append(sql)


class FakeSyncSession:
    def __init__(self) -> None:
        self.listeners: dict[str, list[Any]] = {}

    def trigger_after_begin(self, connection: FakeConnection) -> None:
        for fn in self.listeners.get("after_begin", []):
            fn(self, None, connection)


class FakeAsyncSession:
    def __init__(self) -> None:
        self.rollback_calls = 0
        self.close_calls = 0
        self.sync_session = FakeSyncSession()
        self.connection = FakeConnection()

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def close(self) -> None:
        self.close_calls += 1

    def trigger_after_begin(self) -> None:
        self.sync_session.trigger_after_begin(self.connection)


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
    schema_name: str = "tenant_one",
    pool_size: int = 10,
    max_overflow: int = 10,
) -> TenantDBContext:
    return TenantDBContext(
        tenant_id=tenant_id,
        db_config=DatabaseConfig(
            host="localhost",
            port=5432,
            username="user",
            password="password",
            database_name="shared_db",
            database_uri=database_uri,
            schema_name=schema_name,
            pool_size=pool_size,
            max_overflow=max_overflow,
        ),
    )


def _make_settings() -> Settings:
    return Settings.model_construct(
        TENANCY_DB_STRATEGY="schema",
        USER_DATA_SOURCE={"type": "header"},
    )


def _patch_engine_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> list[FakeAsyncEngine]:
    created_engines: list[FakeAsyncEngine] = []

    def fake_create_async_engine(url: str, **_: object) -> FakeAsyncEngine:
        engine = FakeAsyncEngine(url)
        created_engines.append(engine)
        return engine

    def fake_async_sessionmaker(**_: object):
        def _factory() -> FakeAsyncSession:
            return FakeAsyncSession()

        return _factory

    def fake_listen(target: object, event_name: str, fn: Any) -> None:
        if isinstance(target, FakeSyncSession):
            target.listeners.setdefault(event_name, []).append(fn)

    monkeypatch.setattr(
        "db.tenancy_strategy.create_async_engine", fake_create_async_engine
    )
    monkeypatch.setattr(
        "db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker
    )
    monkeypatch.setattr(
        "db.tenancy_strategy.event.listen", fake_listen
    )
    return created_engines


@pytest.mark.asyncio
async def test_schema_strategy_sets_search_path_on_begin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_engines = _patch_engine_factory(monkeypatch)
    strategy = SchemaTenancyStrategy(_make_settings())
    tenant = _make_tenant_context("tenant_1", schema_name="tenant_one")

    async with strategy.get_session(tenant) as raw_session:
        session = cast(FakeAsyncSession, raw_session)
        assert session.connection.statements == []
        session.trigger_after_begin()
        assert session.connection.statements == [
            'SET LOCAL search_path TO "tenant_one", public'
        ]

    assert session.close_calls == 1
    assert len(created_engines) == 1

    await strategy.teardown()


@pytest.mark.asyncio
async def test_schema_strategy_search_path_reapplied_after_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify search_path is re-applied on subsequent transactions after session.rollback()."""
    _patch_engine_factory(monkeypatch)
    strategy = SchemaTenancyStrategy(_make_settings())
    tenant = _make_tenant_context("tenant_1", schema_name="tenant_one")

    async with strategy.get_session(tenant) as raw_session:
        session = cast(FakeAsyncSession, raw_session)
        # Transaction 1 begins
        session.trigger_after_begin()
        assert session.connection.statements == [
            'SET LOCAL search_path TO "tenant_one", public'
        ]

        # Application encounters an error and rolls back mid-request
        await session.rollback()
        assert session.rollback_calls == 1

        # Transaction 2 begins on the same session/connection
        session.trigger_after_begin()
        assert session.connection.statements == [
            'SET LOCAL search_path TO "tenant_one", public',
            'SET LOCAL search_path TO "tenant_one", public',
        ]

    await strategy.teardown()


@pytest.mark.asyncio
async def test_schema_strategy_pooled_connection_isolation_after_prior_tenant_commit_and_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies isolation when Tenant B reuses a pooled connection after Tenant A commits,
    and Tenant B encounters a rollback mid-request.
    """
    _patch_engine_factory(monkeypatch)
    strategy = SchemaTenancyStrategy(_make_settings())
    tenant_a = _make_tenant_context("tenant_a", schema_name="schema_a")
    tenant_b = _make_tenant_context("tenant_b", schema_name="schema_b")

    # Request 1: Tenant A commits
    async with strategy.get_session(tenant_a) as raw_sess_a:
        sess_a = cast(FakeAsyncSession, raw_sess_a)
        sess_a.trigger_after_begin()
        assert sess_a.connection.statements == [
            'SET LOCAL search_path TO "schema_a", public'
        ]

    # Request 2: Tenant B gets session, rolls back mid-request, retries
    async with strategy.get_session(tenant_b) as raw_sess_b:
        sess_b = cast(FakeAsyncSession, raw_sess_b)
        sess_b.trigger_after_begin()
        assert sess_b.connection.statements == [
            'SET LOCAL search_path TO "schema_b", public'
        ]

        # Tenant B hits rollback (e.g. caught constraint error)
        await sess_b.rollback()

        # Tenant B continues querying in a new transaction
        sess_b.trigger_after_begin()
        assert sess_b.connection.statements == [
            'SET LOCAL search_path TO "schema_b", public',
            'SET LOCAL search_path TO "schema_b", public',
        ]
        # Guarantee schema_a was never set on Tenant B's session
        assert all('schema_a' not in stmt for stmt in sess_b.connection.statements)

    await strategy.teardown()


@pytest.mark.asyncio
async def test_schema_strategy_reuses_shared_engine_for_multiple_tenants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_engines = _patch_engine_factory(monkeypatch)
    strategy = SchemaTenancyStrategy(_make_settings())
    tenant_one = _make_tenant_context("tenant_1", schema_name="tenant_one")
    tenant_two = _make_tenant_context("tenant_2", schema_name="tenant_two")

    async with strategy.get_session(tenant_one) as raw_session_one:
        async with strategy.get_session(tenant_two) as raw_session_two:
            session_one = cast(FakeAsyncSession, raw_session_one)
            session_two = cast(FakeAsyncSession, raw_session_two)
            session_one.trigger_after_begin()
            session_two.trigger_after_begin()
            assert len(created_engines) == 1
            assert session_one.connection.statements == [
                'SET LOCAL search_path TO "tenant_one", public'
            ]
            assert session_two.connection.statements == [
                'SET LOCAL search_path TO "tenant_two", public'
            ]

    await strategy.teardown()


@pytest.mark.asyncio
async def test_schema_strategy_rejects_invalid_schema_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_engine_factory(monkeypatch)
    strategy = SchemaTenancyStrategy(_make_settings())
    tenant = _make_tenant_context("tenant_1", schema_name="tenant-one")

    with pytest.raises(
        ValueError, match="Invalid schema_name for schema strategy: 'tenant-one'"
    ):
        async with strategy.get_session(tenant):
            pass

    await strategy.teardown()


@pytest.mark.asyncio
async def test_schema_strategy_requires_shared_database_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_engine_factory(monkeypatch)
    strategy = SchemaTenancyStrategy(_make_settings())
    tenant_one = _make_tenant_context(
        "tenant_1",
        database_uri="postgresql://shared-db/app",
        schema_name="tenant_one",
    )
    tenant_two = _make_tenant_context(
        "tenant_2",
        database_uri="postgresql://other-db/app",
        schema_name="tenant_two",
    )

    async with strategy.get_session(tenant_one):
        with pytest.raises(
            ValueError,
            match="Schema strategy requires all tenants to share the same database URL",
        ):
            async with strategy.get_session(tenant_two):
                pass

    await strategy.teardown()


@pytest.mark.asyncio
async def test_schema_strategy_concurrent_requests_do_not_leak_search_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_statements: list[tuple[str, list[str]]] = []
    _patch_engine_factory(monkeypatch)

    strategy = SchemaTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="schema",
            USER_DATA_SOURCE={"type": "header"},
        )
    )
    tenants = [
        _make_tenant_context("tenant_1", schema_name="tenant_one"),
        _make_tenant_context("tenant_2", schema_name="tenant_two"),
    ]

    async def run_request(tenant: TenantDBContext) -> None:
        async with strategy.get_session(tenant) as raw_session:
            session = cast(FakeAsyncSession, raw_session)
            session.trigger_after_begin()
            await asyncio.sleep(0)
            observed_statements.append((tenant.tenant_id, list(session.connection.statements)))

    await asyncio.gather(*(run_request(tenants[index % 2]) for index in range(20)))

    for tenant_id, statements in observed_statements:
        expected_schema = "tenant_one" if tenant_id == "tenant_1" else "tenant_two"
        assert statements == [
            f'SET LOCAL search_path TO "{expected_schema}", public',
        ]

    await strategy.teardown()
