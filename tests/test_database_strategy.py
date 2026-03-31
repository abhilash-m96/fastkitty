"""Database-per-tenant strategy tests."""

import asyncio

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


def _make_settings(max_engines: int) -> Settings:
    return Settings.model_construct(
        TENANCY_DB_STRATEGY="database",
        TENANCY_DATABASE_MAX_ENGINES=max_engines,
        USER_DATA_SOURCE={"type": "header"},
    )


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

    monkeypatch.setattr(
        "db.tenancy_strategy.create_async_engine", fake_create_async_engine
    )
    monkeypatch.setattr(
        "db.tenancy_strategy.async_sessionmaker", fake_async_sessionmaker
    )
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
    tenant_one = _make_tenant_context(
        "tenant_1", database_uri="postgresql://db.example.com/tenant-db"
    )
    tenant_two = _make_tenant_context(
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

    tenant_one = _make_tenant_context(
        "tenant_1", database_uri="postgresql://db/tenant_1"
    )
    tenant_two = _make_tenant_context(
        "tenant_2", database_uri="postgresql://db/tenant_2"
    )
    tenant_three = _make_tenant_context(
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

    tenant_one = _make_tenant_context(
        "tenant_1", database_uri="postgresql://db/tenant_1"
    )
    tenant_two = _make_tenant_context(
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
