from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from schemas.tenancy import TenantConfig, TenantSecrets, TenancyDBStrategy


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Request-scoped tenant information shared with DB strategies."""

    tenant_id: str
    tenant_config: TenantConfig
    tenant_secrets: TenantSecrets


class TenancyStrategy(ABC):
    """Async contract for tenancy-aware DB session resolution."""

    strategy_name: TenancyDBStrategy

    @abstractmethod
    async def setup(self, app: FastAPI) -> None:
        """Prepare any strategy-specific resources at application startup."""

    @abstractmethod
    async def teardown(self) -> None:
        """Release any strategy-owned resources at application shutdown."""

    @abstractmethod
    def get_session(
        self, tenant: TenantContext
    ) -> AbstractAsyncContextManager[AsyncSession]:
        """Return a context manager yielding a request-scoped session."""


class _BasePlaceholderTenancyStrategy(TenancyStrategy):
    def __init__(self, settings: Settings):
        self.settings = settings

    async def setup(self, app: FastAPI) -> None:
        app.state.tenancy_strategy = self

    async def teardown(self) -> None:
        return None

    async def get_session(
        self, tenant: TenantContext
    ) -> AsyncGenerator[AsyncSession, None]:
        raise NotImplementedError(
            f"{self.strategy_name!r} tenancy session acquisition is not implemented yet"
        )
        yield tenant  # pragma: no cover


class DatabaseTenancyStrategy(_BasePlaceholderTenancyStrategy):
    strategy_name: TenancyDBStrategy = "database"


class SchemaTenancyStrategy(_BasePlaceholderTenancyStrategy):
    strategy_name: TenancyDBStrategy = "schema"


class RowTenancyStrategy(_BasePlaceholderTenancyStrategy):
    strategy_name: TenancyDBStrategy = "row"


def create_tenancy_strategy(settings: Settings) -> TenancyStrategy:
    """Instantiate the configured tenancy strategy once at startup."""
    strategies: dict[TenancyDBStrategy, type[TenancyStrategy]] = {
        "database": DatabaseTenancyStrategy,
        "schema": SchemaTenancyStrategy,
        "row": RowTenancyStrategy,
    }
    return strategies[settings.TENANCY_DB_STRATEGY](settings)


def get_app_tenancy_strategy(app: FastAPI) -> TenancyStrategy:
    """Read the configured tenancy strategy from FastAPI app state."""
    strategy = getattr(app.state, "tenancy_strategy", None)
    if strategy is None:
        raise RuntimeError("Tenancy strategy has not been initialized on app.state")
    if not isinstance(strategy, TenancyStrategy):
        raise RuntimeError("app.state.tenancy_strategy is not a valid tenancy strategy")
    return strategy
