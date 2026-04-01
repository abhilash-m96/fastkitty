"""Tests for tenancy strategy selection and startup lifecycle wiring."""

import importlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import Settings
from db.tenancy_strategy import (
    DatabaseTenancyStrategy,
    RowTenancyStrategy,
    SchemaTenancyStrategy,
    TenantContext,
    TenancyStrategy,
    create_tenancy_strategy,
    get_app_tenancy_strategy,
)
from schemas.tenancy import DatabaseConfig, TenantConfig, TenantSecrets


def test_create_tenancy_strategy_selects_database_strategy() -> None:
    settings = Settings.model_construct(
        TENANCY_DB_STRATEGY="database",
        USER_DATA_SOURCE={"type": "header"},
    )

    strategy = create_tenancy_strategy(settings)

    assert isinstance(strategy, DatabaseTenancyStrategy)


def test_create_tenancy_strategy_selects_schema_strategy() -> None:
    settings = Settings.model_construct(
        TENANCY_DB_STRATEGY="schema",
        USER_DATA_SOURCE={"type": "header"},
    )

    strategy = create_tenancy_strategy(settings)

    assert isinstance(strategy, SchemaTenancyStrategy)


def test_create_tenancy_strategy_selects_row_strategy() -> None:
    settings = Settings.model_construct(
        TENANCY_DB_STRATEGY="row",
        USER_DATA_SOURCE={"type": "header"},
    )

    strategy = create_tenancy_strategy(settings)

    assert isinstance(strategy, RowTenancyStrategy)


def test_get_app_tenancy_strategy_requires_initialized_state() -> None:
    app = FastAPI()

    with pytest.raises(
        RuntimeError, match="Tenancy strategy has not been initialized on app.state"
    ):
        get_app_tenancy_strategy(app)


@pytest.mark.asyncio
async def test_schema_placeholder_strategy_get_session_raises_not_implemented() -> None:
    settings = Settings.model_construct(
        TENANCY_DB_STRATEGY="schema",
        USER_DATA_SOURCE={"type": "header"},
    )
    strategy = create_tenancy_strategy(settings)
    tenant = TenantContext(
        tenant_id="tenant_1",
        tenant_config=TenantConfig(
            tenant_id="tenant_1",
            display_name="Tenant One",
            is_active=True,
        ),
        tenant_secrets=TenantSecrets(
            tenant_id="tenant_1",
            database_config=DatabaseConfig(
                host="localhost",
                port=5432,
                username="user",
                password="password",
                database_name="tenant_db",
            ),
        ),
    )

    with pytest.raises(
        NotImplementedError,
        match="'schema' tenancy session acquisition is not implemented yet",
    ):
        await anext(strategy.get_session(tenant))


def test_app_startup_initializes_and_exposes_selected_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStrategy(TenancyStrategy):
        strategy_name = "database"

        def __init__(self, settings: Settings):
            self.settings = settings
            self.setup_calls = 0
            self.teardown_calls = 0

        async def setup(self, app: FastAPI) -> None:
            self.setup_calls += 1
            app.state.tenancy_strategy = self

        async def teardown(self) -> None:
            self.teardown_calls += 1

        async def get_session(self, tenant: TenantContext):
            raise NotImplementedError
            yield tenant  # pragma: no cover

    fake_strategy_holder: dict[str, FakeStrategy] = {}

    def fake_create_tenancy_strategy(settings: Settings) -> FakeStrategy:
        strategy = FakeStrategy(settings)
        fake_strategy_holder["strategy"] = strategy
        return strategy

    monkeypatch.setenv("USER_DATA_SOURCE", json.dumps({"type": "header"}))
    monkeypatch.setenv("TENANCY_DB_STRATEGY", "database")
    monkeypatch.setattr(
        "main.create_tenancy_strategy",
        fake_create_tenancy_strategy,
        raising=False,
    )

    from config.settings import get_settings
    import main as main_module

    get_settings.cache_clear()
    main_module = importlib.reload(main_module)
    monkeypatch.setattr(
        main_module, "create_tenancy_strategy", fake_create_tenancy_strategy
    )

    with TestClient(main_module.app) as client:
        strategy = get_app_tenancy_strategy(client.app)
        assert strategy is fake_strategy_holder["strategy"]
        assert strategy.setup_calls == 1
        assert strategy.teardown_calls == 0

    assert fake_strategy_holder["strategy"].teardown_calls == 1
    get_settings.cache_clear()
