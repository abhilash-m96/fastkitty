"""Tests for tenancy strategy selection and startup lifecycle wiring."""

import importlib
import json
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from typing import cast

from config.settings import Settings
from db.tenancy_strategy import (
    DatabaseTenancyStrategy,
    RowTenancyStrategy,
    SchemaTenancyStrategy,
    TenancyStrategy,
    create_tenancy_strategy,
    get_app_tenancy_strategy,
)
from schemas.tenancy import DatabaseConfig


def test_create_tenancy_strategy_selects_database_strategy() -> None:
    settings = Settings.model_construct(
        TENANCY_DB_STRATEGY="database",
        TENANCY_DATABASE_MAX_ENGINES=50,
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


def test_app_startup_initializes_and_exposes_selected_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStrategy(TenancyStrategy):
        strategy_name = "database"

        def __init__(self, settings: Settings) -> None:
            self.settings = settings
            self.setup_calls = 0
            self.teardown_calls = 0

        async def setup(self, app: FastAPI) -> None:
            self.setup_calls += 1
            app.state.tenancy_strategy = self

        async def teardown(self) -> None:
            self.teardown_calls += 1

        @asynccontextmanager
        async def get_session(
            self, db_config: DatabaseConfig
        ) -> AsyncGenerator[AsyncSession, None]:
            raise NotImplementedError
            yield  # pragma: no cover

    fake_strategy_holder: dict[str, FakeStrategy] = {}

    def fake_create_tenancy_strategy(settings: Settings) -> FakeStrategy:
        strategy = FakeStrategy(settings)
        fake_strategy_holder["strategy"] = strategy
        return strategy

    monkeypatch.setenv("USER_DATA_SOURCE", json.dumps({"type": "header"}))
    monkeypatch.setenv("TENANCY_DB_STRATEGY", "database")

    from config.settings import get_settings
    import main as main_module

    get_settings.cache_clear()
    main_module = importlib.reload(main_module)
    monkeypatch.setattr(
        main_module, "create_tenancy_strategy", fake_create_tenancy_strategy
    )

    with TestClient(main_module.app) as client:
        fastapi_app = cast(FastAPI, client.app)
        strategy = cast(FakeStrategy, get_app_tenancy_strategy(fastapi_app))
        assert strategy is fake_strategy_holder["strategy"]
        assert strategy.setup_calls == 1
        assert strategy.teardown_calls == 0

    assert fake_strategy_holder["strategy"].teardown_calls == 1
    get_settings.cache_clear()
