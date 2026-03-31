from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import Settings
from db.session import PoolConfig
from schemas.tenancy import (
    DatabaseConfig,
    TenancyDBStrategy,
    TenantConfig,
    TenantSecrets,
)


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


@dataclass(slots=True)
class _DatabaseEngineEntry:
    db_uri: str
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    pool_config: PoolConfig
    active_sessions: int = 0
    idle_event: asyncio.Event | None = None

    def __post_init__(self) -> None:
        if self.idle_event is None:
            self.idle_event = asyncio.Event()
            self.idle_event.set()


@dataclass(slots=True)
class _SharedSchemaEngineEntry:
    db_uri: str
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    pool_config: PoolConfig


class _BasePlaceholderTenancyStrategy(TenancyStrategy):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def setup(self, app: FastAPI) -> None:
        app.state.tenancy_strategy = self

    async def teardown(self) -> None:
        return None

    def get_session(
        self, tenant: TenantContext
    ) -> AbstractAsyncContextManager[AsyncSession]:
        raise NotImplementedError(
            f"{self.strategy_name!r} tenancy session acquisition is not implemented yet"
        )


class DatabaseTenancyStrategy(TenancyStrategy):
    strategy_name: TenancyDBStrategy = "database"

    def __init__(self, settings: Settings) -> None:
        self._max_engines = settings.TENANCY_DATABASE_MAX_ENGINES
        self._engines: OrderedDict[str, _DatabaseEngineEntry] = OrderedDict()
        self._registry_lock = asyncio.Lock()
        self._dispose_tasks: set[asyncio.Task[None]] = set()

    async def setup(self, app: FastAPI) -> None:
        app.state.tenancy_strategy = self

    @asynccontextmanager
    async def get_session(
        self, tenant: TenantContext
    ) -> AsyncGenerator[AsyncSession, None]:
        db_config = tenant.tenant_secrets.database_config
        entry = await self._acquire_entry(db_config)
        session = entry.session_factory()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
            await self._release_entry(entry)

    async def teardown(self) -> None:
        async with self._registry_lock:
            entries = list(self._engines.values())
            self._engines.clear()
        pending = list(self._dispose_tasks)
        self._dispose_tasks.clear()
        await asyncio.gather(
            *[self._dispose_entry(entry) for entry in entries],
            *pending,
        )

    async def _acquire_entry(self, db_config: DatabaseConfig) -> _DatabaseEngineEntry:
        db_uri = db_config.database_uri
        entry_to_dispose: _DatabaseEngineEntry | None = None

        async with self._registry_lock:
            entry = self._engines.get(db_uri)
            if entry is None:
                entry = self._create_entry(db_uri=db_uri, db_config=db_config)
                self._engines[db_uri] = entry
            else:
                self._validate_pool_config(entry=entry, db_config=db_config)
                self._engines.move_to_end(db_uri)

            entry.active_sessions += 1
            if entry.idle_event is not None:
                entry.idle_event.clear()

            if len(self._engines) > self._max_engines:
                _, entry_to_dispose = self._engines.popitem(last=False)

        if entry_to_dispose is not None:
            task = self._schedule_dispose(entry_to_dispose)
            self._dispose_tasks.add(task)

        return entry

    async def _release_entry(self, entry: _DatabaseEngineEntry) -> None:
        async with self._registry_lock:
            entry.active_sessions -= 1
            if entry.active_sessions == 0 and entry.idle_event is not None:
                entry.idle_event.set()

    def _create_entry(
        self, *, db_uri: str, db_config: DatabaseConfig
    ) -> _DatabaseEngineEntry:
        pool_config = PoolConfig(
            db_uri=db_uri,
            pool_size=db_config.pool_size,
            max_overflow=db_config.max_overflow,
            pool_recycle=db_config.pool_recycle,
            pool_pre_ping=db_config.pool_pre_ping,
        )
        engine = create_async_engine(
            db_uri,
            pool_size=pool_config.pool_size,
            max_overflow=pool_config.max_overflow,
            pool_recycle=pool_config.pool_recycle,
            pool_pre_ping=pool_config.pool_pre_ping,
            echo=False,
        )
        session_factory = async_sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        return _DatabaseEngineEntry(
            db_uri=db_uri,
            engine=engine,
            session_factory=session_factory,
            pool_config=pool_config,
        )

    def _validate_pool_config(
        self, *, entry: _DatabaseEngineEntry, db_config: DatabaseConfig
    ) -> None:
        expected = PoolConfig(
            db_uri=entry.db_uri,
            pool_size=db_config.pool_size,
            max_overflow=db_config.max_overflow,
            pool_recycle=db_config.pool_recycle,
            pool_pre_ping=db_config.pool_pre_ping,
        )
        if entry.pool_config != expected:
            raise ValueError(
                "Database strategy received conflicting pool settings for the same "
                f"database URL: {entry.db_uri}"
            )

    def _schedule_dispose(self, entry: _DatabaseEngineEntry) -> asyncio.Task[None]:
        task = asyncio.create_task(self._dispose_entry(entry))
        task.add_done_callback(self._dispose_tasks.discard)
        return task

    async def _dispose_entry(self, entry: _DatabaseEngineEntry) -> None:
        if entry.idle_event is not None:
            await entry.idle_event.wait()
        await entry.engine.dispose()


class SchemaTenancyStrategy(TenancyStrategy):
    strategy_name: TenancyDBStrategy = "schema"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._shared_entry: _SharedSchemaEngineEntry | None = None
        self._registry_lock = asyncio.Lock()

    async def setup(self, app: FastAPI) -> None:
        app.state.tenancy_strategy = self

    @asynccontextmanager
    async def get_session(
        self, tenant: TenantContext
    ) -> AsyncGenerator[AsyncSession, None]:
        db_config = tenant.tenant_secrets.database_config
        schema_name = _normalize_schema_name(db_config)
        entry = await self._get_or_create_entry(db_config)
        session = entry.session_factory()
        try:
            await session.execute(text(f"SET search_path TO {schema_name}, public"))
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            try:
                await session.execute(text("RESET search_path"))
            finally:
                await session.close()

    async def teardown(self) -> None:
        async with self._registry_lock:
            entry = self._shared_entry
            self._shared_entry = None
        if entry is not None:
            await entry.engine.dispose()

    async def _get_or_create_entry(
        self, db_config: DatabaseConfig
    ) -> _SharedSchemaEngineEntry:
        db_uri = db_config.database_uri
        async with self._registry_lock:
            if self._shared_entry is None:
                self._shared_entry = self._create_entry(db_uri=db_uri, db_config=db_config)
            else:
                if self._shared_entry.db_uri != db_uri:
                    raise ValueError(
                        "Schema strategy requires all tenants to share the same "
                        f"database URL, got: {db_uri}"
                    )
                self._validate_shared_config(entry=self._shared_entry, db_config=db_config)
            return self._shared_entry

    def _create_entry(
        self, *, db_uri: str, db_config: DatabaseConfig
    ) -> _SharedSchemaEngineEntry:
        pool_config = PoolConfig(
            db_uri=db_uri,
            pool_size=db_config.pool_size,
            max_overflow=db_config.max_overflow,
            pool_recycle=db_config.pool_recycle,
            pool_pre_ping=db_config.pool_pre_ping,
        )
        engine = create_async_engine(
            db_uri,
            pool_size=pool_config.pool_size,
            max_overflow=pool_config.max_overflow,
            pool_recycle=pool_config.pool_recycle,
            pool_pre_ping=pool_config.pool_pre_ping,
            echo=False,
        )
        session_factory = async_sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        return _SharedSchemaEngineEntry(
            db_uri=db_uri,
            engine=engine,
            session_factory=session_factory,
            pool_config=pool_config,
        )

    def _validate_shared_config(
        self,
        *,
        entry: _SharedSchemaEngineEntry,
        db_config: DatabaseConfig,
    ) -> None:
        expected = PoolConfig(
            db_uri=entry.db_uri,
            pool_size=db_config.pool_size,
            max_overflow=db_config.max_overflow,
            pool_recycle=db_config.pool_recycle,
            pool_pre_ping=db_config.pool_pre_ping,
        )
        if entry.pool_config != expected:
            raise ValueError(
                "Schema strategy received conflicting pool settings for the shared "
                f"database URL: {entry.db_uri}"
            )


class RowTenancyStrategy(_BasePlaceholderTenancyStrategy):
    strategy_name: TenancyDBStrategy = "row"


def create_tenancy_strategy(settings: Settings) -> TenancyStrategy:
    """Instantiate the configured tenancy strategy once at startup."""
    strategy = settings.TENANCY_DB_STRATEGY
    if strategy == "database":
        return DatabaseTenancyStrategy(settings)
    if strategy == "schema":
        return SchemaTenancyStrategy(settings)
    if strategy == "row":
        return RowTenancyStrategy(settings)
    raise ValueError(f"Unknown tenancy strategy: {strategy!r}")


def get_app_tenancy_strategy(app: FastAPI) -> TenancyStrategy:
    """Read the configured tenancy strategy from FastAPI app state."""
    strategy = getattr(app.state, "tenancy_strategy", None)
    if strategy is None:
        raise RuntimeError("Tenancy strategy has not been initialized on app.state")
    if not isinstance(strategy, TenancyStrategy):
        raise RuntimeError("app.state.tenancy_strategy is not a valid tenancy strategy")
    return strategy


def _normalize_schema_name(db_config: DatabaseConfig) -> str:
    schema_name = db_config.schema_name
    if not schema_name:
        raise ValueError("Schema strategy requires database_config.schema_name")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema_name):
        raise ValueError(f"Invalid schema_name for schema strategy: {schema_name!r}")
    return schema_name
