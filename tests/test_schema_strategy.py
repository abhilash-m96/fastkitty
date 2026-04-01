"""Schema-per-tenant strategy tests."""

import asyncio

import pytest
from typing import cast

from config.settings import Settings
from db.tenancy_strategy import SchemaTenancyStrategy, TenantContext
from schemas.tenancy import DatabaseConfig, TenantConfig, TenantSecrets


class FakeAsyncSession:
    def __init__(self) -> None:
        self.rollback_calls = 0
        self.close_calls = 0
        self.statements: list[str] = []

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))

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
    schema_name: str = "tenant_one",
    pool_size: int = 10,
    max_overflow: int = 10,
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
                schema_name=schema_name,
                pool_size=pool_size,
                max_overflow=max_overflow,
            ),
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

    monkeypatch.setattr(
        "db.tenancy_strategy.create_async_engine", fake_create_async_engine
    )
    monkeypatch.setattr(
        "db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker
    )
    return created_engines


@pytest.mark.asyncio
async def test_schema_strategy_sets_and_resets_search_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_engines = _patch_engine_factory(monkeypatch)
    strategy = SchemaTenancyStrategy(_make_settings())
    tenant = _make_tenant_context("tenant_1", schema_name="tenant_one")

    async with strategy.get_session(tenant) as raw_session:
        session = cast(FakeAsyncSession, raw_session)
        assert session.statements == ["SET search_path TO tenant_one, public"]

    assert session.statements == [
        "SET search_path TO tenant_one, public",
        "RESET search_path",
    ]
    assert session.close_calls == 1
    assert len(created_engines) == 1

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
            assert len(created_engines) == 1
            assert session_one.statements == ["SET search_path TO tenant_one, public"]
            assert session_two.statements == ["SET search_path TO tenant_two, public"]

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

    def fake_create_async_engine(url: str, **_: object) -> FakeAsyncEngine:
        return FakeAsyncEngine(url)

    def fake_async_sessionmaker(**_: object):
        def _factory() -> FakeAsyncSession:
            return FakeAsyncSession()

        return _factory

    monkeypatch.setattr(
        "db.tenancy_strategy.create_async_engine", fake_create_async_engine
    )
    monkeypatch.setattr(
        "db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker
    )

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

    async def run_request(tenant: TenantContext) -> None:
        async with strategy.get_session(tenant) as raw_session:
            await asyncio.sleep(0)
        session = cast(FakeAsyncSession, raw_session)
        observed_statements.append((tenant.tenant_id, session.statements))

    await asyncio.gather(*(run_request(tenants[index % 2]) for index in range(20)))

    for tenant_id, statements in observed_statements:
        expected_schema = "tenant_one" if tenant_id == "tenant_1" else "tenant_two"
        assert statements == [
            f"SET search_path TO {expected_schema}, public",
            "RESET search_path",
        ]

    await strategy.teardown()
