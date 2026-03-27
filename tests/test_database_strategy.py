"""Database-per-tenant strategy tests."""

import asyncio
from collections.abc import Callable

import pytest

from config.settings import Settings
from db.tenancy_strategy import DatabaseTenancyStrategy, TenantContext
from schemas.tenancy import DatabaseConfig, TenantConfig, TenantSecrets


class FakeAsyncSession:
    def __init__(self) -> None:
        self.rollback_calls = 0
        self.close_calls = 0

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class BlockingAsyncSession(FakeAsyncSession):
    def __init__(self, on_close: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.on_close = on_close

    async def close(self) -> None:
        await super().close()
        if self.on_close is not None:
            self.on_close()


class FakeAsyncEngine:
    def __init__(self, url: str) -> None:
        self.url = url
        self.dispose_calls = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1


def _make_tenant_context(
    tenant_id: str,
    *,
    database_uri: str,
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
                database_name=f"db_{tenant_id}",
                database_uri=database_uri,
                pool_size=pool_size,
                max_overflow=max_overflow,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_database_strategy_reuses_engine_for_same_database_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_engines: list[FakeAsyncEngine] = []

    def fake_create_async_engine(url: str, **_: object) -> FakeAsyncEngine:
        engine = FakeAsyncEngine(url)
        created_engines.append(engine)
        return engine

    def fake_async_sessionmaker(**_: object):
        def _factory() -> FakeAsyncSession:
            return FakeAsyncSession()

        return _factory

    monkeypatch.setattr("db.tenancy_strategy.create_async_engine", fake_create_async_engine)
    monkeypatch.setattr("db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker)

    strategy = DatabaseTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="database",
            TENANCY_DATABASE_MAX_ENGINES=5,
            USER_DATA_SOURCE={"type": "header"},
        )
    )
    tenant_one = _make_tenant_context(
        "tenant_1", database_uri="postgresql://db.example.com/tenant-db"
    )
    tenant_two = _make_tenant_context(
        "tenant_2", database_uri="postgresql://db.example.com/tenant-db"
    )

    session_generator_one = strategy.get_session(tenant_one)
    session_one = await anext(session_generator_one)
    session_generator_two = strategy.get_session(tenant_two)
    session_two = await anext(session_generator_two)

    assert isinstance(session_one, FakeAsyncSession)
    assert isinstance(session_two, FakeAsyncSession)
    assert len(created_engines) == 1
    assert created_engines[0].url == "postgresql+asyncpg://db.example.com/tenant-db"

    await session_generator_one.aclose()
    await session_generator_two.aclose()
    await strategy.teardown()


@pytest.mark.asyncio
async def test_database_strategy_evicts_lru_engine_and_disposes_idle_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engines_by_url: dict[str, FakeAsyncEngine] = {}

    def fake_create_async_engine(url: str, **_: object) -> FakeAsyncEngine:
        engine = FakeAsyncEngine(url)
        engines_by_url[url] = engine
        return engine

    def fake_async_sessionmaker(**_: object):
        def _factory() -> FakeAsyncSession:
            return FakeAsyncSession()

        return _factory

    monkeypatch.setattr("db.tenancy_strategy.create_async_engine", fake_create_async_engine)
    monkeypatch.setattr("db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker)

    strategy = DatabaseTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="database",
            TENANCY_DATABASE_MAX_ENGINES=2,
            USER_DATA_SOURCE={"type": "header"},
        )
    )
    tenant_one = _make_tenant_context("tenant_1", database_uri="postgresql://db/tenant_1")
    tenant_two = _make_tenant_context("tenant_2", database_uri="postgresql://db/tenant_2")
    tenant_three = _make_tenant_context(
        "tenant_3", database_uri="postgresql://db/tenant_3"
    )

    for tenant in (tenant_one, tenant_two, tenant_three):
        session_generator = strategy.get_session(tenant)
        await anext(session_generator)
        await session_generator.aclose()

    await asyncio.sleep(0)

    assert engines_by_url["postgresql+asyncpg://db/tenant_1"].dispose_calls == 1
    assert len(strategy._engines) == 2

    await strategy.teardown()


@pytest.mark.asyncio
async def test_database_strategy_waits_for_in_flight_session_before_dispose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engines_by_url: dict[str, FakeAsyncEngine] = {}

    def fake_create_async_engine(url: str, **_: object) -> FakeAsyncEngine:
        engine = FakeAsyncEngine(url)
        engines_by_url[url] = engine
        return engine

    def fake_async_sessionmaker(**_: object):
        def _factory() -> FakeAsyncSession:
            return FakeAsyncSession()

        return _factory

    monkeypatch.setattr("db.tenancy_strategy.create_async_engine", fake_create_async_engine)
    monkeypatch.setattr("db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker)

    strategy = DatabaseTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="database",
            TENANCY_DATABASE_MAX_ENGINES=1,
            USER_DATA_SOURCE={"type": "header"},
        )
    )
    tenant_one = _make_tenant_context("tenant_1", database_uri="postgresql://db/tenant_1")
    tenant_two = _make_tenant_context("tenant_2", database_uri="postgresql://db/tenant_2")

    session_generator_one = strategy.get_session(tenant_one)
    await anext(session_generator_one)
    session_generator_two = strategy.get_session(tenant_two)
    await anext(session_generator_two)
    await session_generator_two.aclose()
    await asyncio.sleep(0)

    assert engines_by_url["postgresql+asyncpg://db/tenant_1"].dispose_calls == 0

    await session_generator_one.aclose()
    await asyncio.sleep(0)

    assert engines_by_url["postgresql+asyncpg://db/tenant_1"].dispose_calls == 1

    await strategy.teardown()


@pytest.mark.asyncio
async def test_database_strategy_handles_concurrent_requests_with_shared_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_engines: list[FakeAsyncEngine] = []

    def fake_create_async_engine(url: str, **_: object) -> FakeAsyncEngine:
        engine = FakeAsyncEngine(url)
        created_engines.append(engine)
        return engine

    def fake_async_sessionmaker(**_: object):
        def _factory() -> FakeAsyncSession:
            return FakeAsyncSession()

        return _factory

    monkeypatch.setattr("db.tenancy_strategy.create_async_engine", fake_create_async_engine)
    monkeypatch.setattr("db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker)

    strategy = DatabaseTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="database",
            TENANCY_DATABASE_MAX_ENGINES=5,
            USER_DATA_SOURCE={"type": "header"},
        )
    )
    shared_tenant_one = _make_tenant_context(
        "tenant_1", database_uri="postgresql://db.example.com/shared"
    )
    shared_tenant_two = _make_tenant_context(
        "tenant_2", database_uri="postgresql://db.example.com/shared"
    )

    async def run_request(tenant: TenantContext) -> None:
        generator = strategy.get_session(tenant)
        session = await anext(generator)
        assert isinstance(session, FakeAsyncSession)
        await asyncio.sleep(0)
        await generator.aclose()

    await asyncio.gather(
        *(run_request(shared_tenant_one if index % 2 == 0 else shared_tenant_two) for index in range(20))
    )

    assert len(created_engines) == 1
    await strategy.teardown()


@pytest.mark.asyncio
async def test_database_strategy_eviction_under_concurrency_keeps_requests_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engines_by_url: dict[str, FakeAsyncEngine] = {}
    close_events: dict[str, asyncio.Event] = {}

    def fake_create_async_engine(url: str, **_: object) -> FakeAsyncEngine:
        engine = FakeAsyncEngine(url)
        engines_by_url[url] = engine
        close_events[url] = asyncio.Event()
        return engine

    def fake_async_sessionmaker(bind: FakeAsyncEngine, **_: object):
        def _factory() -> BlockingAsyncSession:
            return BlockingAsyncSession(on_close=close_events[bind.url].set)

        return _factory

    monkeypatch.setattr("db.tenancy_strategy.create_async_engine", fake_create_async_engine)
    monkeypatch.setattr("db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker)

    strategy = DatabaseTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="database",
            TENANCY_DATABASE_MAX_ENGINES=2,
            USER_DATA_SOURCE={"type": "header"},
        )
    )
    tenant_one = _make_tenant_context("tenant_1", database_uri="postgresql://db/tenant_1")
    tenant_two = _make_tenant_context("tenant_2", database_uri="postgresql://db/tenant_2")
    tenant_three = _make_tenant_context("tenant_3", database_uri="postgresql://db/tenant_3")

    generator_one = strategy.get_session(tenant_one)
    session_one = await anext(generator_one)
    assert isinstance(session_one, BlockingAsyncSession)

    generator_two = strategy.get_session(tenant_two)
    await anext(generator_two)
    await generator_two.aclose()

    generator_three = strategy.get_session(tenant_three)
    await anext(generator_three)
    await generator_three.aclose()
    await asyncio.sleep(0)

    assert engines_by_url["postgresql+asyncpg://db/tenant_1"].dispose_calls == 0

    await generator_one.aclose()
    await close_events["postgresql+asyncpg://db/tenant_1"].wait()
    await asyncio.sleep(0)

    assert engines_by_url["postgresql+asyncpg://db/tenant_1"].dispose_calls == 1
    await strategy.teardown()
