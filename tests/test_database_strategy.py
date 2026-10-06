"""Database-per-tenant strategy tests."""

import asyncio
from collections.abc import Callable

import pytest

from config.settings import Settings
from db.tenancy_strategy import DatabaseTenancyStrategy, TenantDBContext
from schemas.tenancy import DatabaseConfig


class FakeSyncSession:
    def __init__(self) -> None:
        self.listeners: dict[str, list[object]] = {}


class FakeAsyncSession:
    def __init__(self) -> None:
        self.rollback_calls = 0
        self.close_calls = 0
        self.sync_session = FakeSyncSession()

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


def _make_tenant_db_context(
    tenant_id: str,
    *,
    database_uri: str,
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
            database_name=f"db_{tenant_id}",
            database_uri=database_uri,
            pool_size=pool_size,
            max_overflow=max_overflow,
        ),
    )


def _make_settings(max_engines: int) -> Settings:
    return Settings.model_construct(
        TENANCY_DB_STRATEGY="database",
        TENANCY_DATABASE_MAX_ENGINES=max_engines,
        USER_DATA_SOURCE={"type": "header"},
    )


@pytest.fixture(autouse=True)
def _patch_event_listen(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy import event as sa_event

    orig_listen = sa_event.listen

    def fake_listen(target: object, event_name: str, fn: object) -> None:
        if isinstance(target, FakeSyncSession):
            target.listeners.setdefault(event_name, []).append(fn)
            return
        orig_listen(target, event_name, fn)

    monkeypatch.setattr("db.tenancy_strategy.event.listen", fake_listen)


def _patch_engine_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, FakeAsyncEngine]:
    engines_by_url: dict[str, FakeAsyncEngine] = {}

    def fake_create_async_engine(url: str, **_: object) -> FakeAsyncEngine:
        engine = FakeAsyncEngine(url)
        engines_by_url[url] = engine
        return engine

    def fake_async_sessionmaker(**_: object):
        def _factory() -> FakeAsyncSession:
            return FakeAsyncSession()

        return _factory

    def fake_listen(target: object, event_name: str, fn: object) -> None:
        if isinstance(target, FakeSyncSession):
            target.listeners.setdefault(event_name, []).append(fn)

    monkeypatch.setattr(
        "db.tenancy_strategy.create_async_engine", fake_create_async_engine
    )
    monkeypatch.setattr(
        "db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker
    )
    monkeypatch.setattr("db.tenancy_strategy.event.listen", fake_listen)
    return engines_by_url


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

    monkeypatch.setattr(
        "db.tenancy_strategy.create_async_engine", fake_create_async_engine
    )
    monkeypatch.setattr(
        "db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker
    )

    strategy = DatabaseTenancyStrategy(_make_settings(max_engines=5))
    tenant_one = _make_tenant_db_context(
        "tenant_1", database_uri="postgresql://db.example.com/tenant-db"
    )
    tenant_two = _make_tenant_db_context(
        "tenant_2", database_uri="postgresql://db.example.com/tenant-db"
    )

    async with strategy.get_session(tenant_one) as session_one:
        async with strategy.get_session(tenant_two) as session_two:
            assert isinstance(session_one, FakeAsyncSession)
            assert isinstance(session_two, FakeAsyncSession)
            assert len(created_engines) == 1
            assert (
                created_engines[0].url
                == "postgresql+asyncpg://db.example.com/tenant-db"
            )

    await strategy.teardown()


@pytest.mark.asyncio
async def test_database_strategy_evicts_lru_engine_and_disposes_idle_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engines_by_url = _patch_engine_factory(monkeypatch)
    strategy = DatabaseTenancyStrategy(_make_settings(max_engines=2))

    tenant_one = _make_tenant_db_context(
        "tenant_1", database_uri="postgresql://db/tenant_1"
    )
    tenant_two = _make_tenant_db_context(
        "tenant_2", database_uri="postgresql://db/tenant_2"
    )
    tenant_three = _make_tenant_db_context(
        "tenant_3", database_uri="postgresql://db/tenant_3"
    )

    for tenant in (tenant_one, tenant_two, tenant_three):
        async with strategy.get_session(tenant):
            pass

    await asyncio.sleep(0)

    assert engines_by_url["postgresql+asyncpg://db/tenant_1"].dispose_calls == 1
    assert len(strategy._engines) == 2

    await strategy.teardown()


@pytest.mark.asyncio
async def test_database_strategy_waits_for_in_flight_session_before_dispose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engines_by_url = _patch_engine_factory(monkeypatch)
    strategy = DatabaseTenancyStrategy(_make_settings(max_engines=1))

    tenant_one = _make_tenant_db_context(
        "tenant_1", database_uri="postgresql://db/tenant_1"
    )
    tenant_two = _make_tenant_db_context(
        "tenant_2", database_uri="postgresql://db/tenant_2"
    )

    async with strategy.get_session(tenant_one) as _:
        async with strategy.get_session(tenant_two) as _:
            pass

        await asyncio.sleep(0)
        # tenant_one session still open — dispose must not have run yet
        assert engines_by_url["postgresql+asyncpg://db/tenant_1"].dispose_calls == 0

    await asyncio.sleep(0)
    # tenant_one session now closed — dispose should have run
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

    monkeypatch.setattr(
        "db.tenancy_strategy.create_async_engine", fake_create_async_engine
    )
    monkeypatch.setattr(
        "db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker
    )

    strategy = DatabaseTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="database",
            TENANCY_DATABASE_MAX_ENGINES=5,
            USER_DATA_SOURCE={"type": "header"},
        )
    )
    shared_tenant_one = _make_tenant_db_context(
        "tenant_1", database_uri="postgresql://db.example.com/shared"
    )
    shared_tenant_two = _make_tenant_db_context(
        "tenant_2", database_uri="postgresql://db.example.com/shared"
    )

    async def run_request(tenant: TenantDBContext) -> None:
        async with strategy.get_session(tenant) as session:
            assert isinstance(session, FakeAsyncSession)
            await asyncio.sleep(0)

    await asyncio.gather(
        *(
            run_request(shared_tenant_one if index % 2 == 0 else shared_tenant_two)
            for index in range(20)
        )
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

    monkeypatch.setattr(
        "db.tenancy_strategy.create_async_engine", fake_create_async_engine
    )
    monkeypatch.setattr(
        "db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker
    )

    strategy = DatabaseTenancyStrategy(
        Settings.model_construct(
            TENANCY_DB_STRATEGY="database",
            TENANCY_DATABASE_MAX_ENGINES=2,
            USER_DATA_SOURCE={"type": "header"},
        )
    )
    tenant_one = _make_tenant_db_context(
        "tenant_1", database_uri="postgresql://db/tenant_1"
    )
    tenant_two = _make_tenant_db_context(
        "tenant_2", database_uri="postgresql://db/tenant_2"
    )
    tenant_three = _make_tenant_db_context(
        "tenant_3", database_uri="postgresql://db/tenant_3"
    )

    # Keep tenant_one session open while eviction happens
    async with strategy.get_session(tenant_one) as session_one:
        assert isinstance(session_one, BlockingAsyncSession)

        async with strategy.get_session(tenant_two):
            pass

        async with strategy.get_session(tenant_three):
            pass

        await asyncio.sleep(0)
        # tenant_one still in flight — must not be disposed yet
        assert engines_by_url["postgresql+asyncpg://db/tenant_1"].dispose_calls == 0

    await close_events["postgresql+asyncpg://db/tenant_1"].wait()
    await asyncio.sleep(0)
    # tenant_one session closed — dispose should have run
    assert engines_by_url["postgresql+asyncpg://db/tenant_1"].dispose_calls == 1

    await strategy.teardown()
