from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from collections import OrderedDict
from dataclasses import dataclass

from fastapi import FastAPI
from sqlalchemy import event, text
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import Settings, TenancyDBStrategy
from models.base import TenantAwareModel
from schemas.tenancy import DatabaseConfig, TenantConfig, TenantSecrets


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
    async def get_session(
        self, tenant: TenantContext
    ) -> AsyncGenerator[AsyncSession, None]:
        """Yield a request-scoped session for the resolved tenant context."""


@dataclass(slots=True)
class _DatabaseEngineEntry:
    db_uri: str
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    pool_size: int
    max_overflow: int
    pool_recycle: int
    pool_pre_ping: bool
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
    pool_size: int
    max_overflow: int
    pool_recycle: int
    pool_pre_ping: bool


_current_row_tenant_id: ContextVar[str | None] = ContextVar(
    "current_row_tenant_id", default=None
)


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

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._max_engines = settings.TENANCY_DATABASE_MAX_ENGINES
        self._engines: OrderedDict[str, _DatabaseEngineEntry] = OrderedDict()
        self._registry_lock = asyncio.Lock()
        self._dispose_tasks: set[asyncio.Task[None]] = set()

    async def get_session(
        self, tenant: TenantContext
    ) -> AsyncGenerator[AsyncSession, None]:
        entry = await self._acquire_entry(tenant.tenant_secrets.database_config)
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
        dispose_tasks = [self._schedule_dispose(entry) for entry in entries]
        if self._dispose_tasks:
            dispose_tasks.extend(self._dispose_tasks)
        if dispose_tasks:
            await asyncio.gather(*dispose_tasks)
        self._dispose_tasks.clear()

    async def _acquire_entry(self, db_config: DatabaseConfig) -> _DatabaseEngineEntry:
        db_uri = _build_db_uri(db_config)
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
            self._dispose_tasks.add(self._schedule_dispose(entry_to_dispose))

        return entry

    async def _release_entry(self, entry: _DatabaseEngineEntry) -> None:
        async with self._registry_lock:
            entry.active_sessions -= 1
            if entry.active_sessions == 0 and entry.idle_event is not None:
                entry.idle_event.set()

    def _create_entry(
        self,
        *,
        db_uri: str,
        db_config: DatabaseConfig,
    ) -> _DatabaseEngineEntry:
        engine = create_async_engine(
            db_uri,
            pool_size=db_config.pool_size,
            max_overflow=db_config.max_overflow,
            pool_recycle=db_config.pool_recycle,
            pool_pre_ping=db_config.pool_pre_ping,
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
            pool_size=db_config.pool_size,
            max_overflow=db_config.max_overflow,
            pool_recycle=db_config.pool_recycle,
            pool_pre_ping=db_config.pool_pre_ping,
        )

    def _validate_pool_config(
        self,
        *,
        entry: _DatabaseEngineEntry,
        db_config: DatabaseConfig,
    ) -> None:
        if (
            entry.pool_size,
            entry.max_overflow,
            entry.pool_recycle,
            entry.pool_pre_ping,
        ) == (
            db_config.pool_size,
            db_config.max_overflow,
            db_config.pool_recycle,
            db_config.pool_pre_ping,
        ):
            return

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


class SchemaTenancyStrategy(_BasePlaceholderTenancyStrategy):
    strategy_name: TenancyDBStrategy = "schema"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._shared_entry: _SharedSchemaEngineEntry | None = None
        self._registry_lock = asyncio.Lock()

    async def get_session(
        self, tenant: TenantContext
    ) -> AsyncGenerator[AsyncSession, None]:
        entry = await self._get_or_create_entry(tenant.tenant_secrets.database_config)
        schema_name = _normalize_schema_name(tenant.tenant_secrets.database_config)
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
        db_uri = _build_db_uri(db_config)
        async with self._registry_lock:
            if self._shared_entry is None:
                self._shared_entry = self._create_entry(db_uri=db_uri, db_config=db_config)
            else:
                self._validate_shared_config(entry=self._shared_entry, db_config=db_config)
                if self._shared_entry.db_uri != db_uri:
                    raise ValueError(
                        "Schema strategy requires all tenants to share the same "
                        f"database URL, got: {db_uri}"
                    )
            return self._shared_entry

    def _create_entry(
        self,
        *,
        db_uri: str,
        db_config: DatabaseConfig,
    ) -> _SharedSchemaEngineEntry:
        engine = create_async_engine(
            db_uri,
            pool_size=db_config.pool_size,
            max_overflow=db_config.max_overflow,
            pool_recycle=db_config.pool_recycle,
            pool_pre_ping=db_config.pool_pre_ping,
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
            pool_size=db_config.pool_size,
            max_overflow=db_config.max_overflow,
            pool_recycle=db_config.pool_recycle,
            pool_pre_ping=db_config.pool_pre_ping,
        )

    def _validate_shared_config(
        self,
        *,
        entry: _SharedSchemaEngineEntry,
        db_config: DatabaseConfig,
    ) -> None:
        if (
            entry.pool_size,
            entry.max_overflow,
            entry.pool_recycle,
            entry.pool_pre_ping,
        ) == (
            db_config.pool_size,
            db_config.max_overflow,
            db_config.pool_recycle,
            db_config.pool_pre_ping,
        ):
            return

        raise ValueError(
            "Schema strategy received conflicting pool settings for the shared "
            f"database URL: {entry.db_uri}"
        )


class RowTenancyStrategy(_BasePlaceholderTenancyStrategy):
    strategy_name: TenancyDBStrategy = "row"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._shared_entry: _SharedSchemaEngineEntry | None = None
        self._registry_lock = asyncio.Lock()

    async def get_session(
        self, tenant: TenantContext
    ) -> AsyncGenerator[AsyncSession, None]:
        entry = await self._get_or_create_entry(tenant.tenant_secrets.database_config)
        session = entry.session_factory()
        _configure_row_session(session)
        token = set_current_row_tenant_id(tenant.tenant_id)
        session.info["tenant_id"] = tenant.tenant_id
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            reset_current_row_tenant_id(token)
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
        db_uri = _build_db_uri(db_config)
        async with self._registry_lock:
            if self._shared_entry is None:
                self._shared_entry = _create_shared_engine_entry(
                    db_uri=db_uri,
                    db_config=db_config,
                )
            else:
                _validate_shared_pool_config(entry=self._shared_entry, db_config=db_config)
                if self._shared_entry.db_uri != db_uri:
                    raise ValueError(
                        "Row strategy requires all tenants to share the same "
                        f"database URL, got: {db_uri}"
                    )
            return self._shared_entry


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


def _build_db_uri(db_config: DatabaseConfig) -> str:
    db_uri = db_config.database_uri or (
        f"{db_config.dialect}://{db_config.username}:{db_config.password}"
        f"@{db_config.host}:{db_config.port}/{db_config.database_name}"
    )
    if db_uri.startswith("postgresql+asyncpg://"):
        return db_uri
    if db_uri.startswith("postgresql://"):
        return db_uri.replace("postgresql://", "postgresql+asyncpg://", 1)
    if db_uri.startswith("postgres://"):
        return db_uri.replace("postgres://", "postgresql+asyncpg://", 1)
    return db_uri


def _normalize_schema_name(db_config: DatabaseConfig) -> str:
    schema_name = db_config.schema_name
    if not schema_name:
        raise ValueError("Schema strategy requires database_config.schema_name")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema_name):
        raise ValueError(f"Invalid schema_name for schema strategy: {schema_name!r}")
    return schema_name


def set_current_row_tenant_id(tenant_id: str) -> Token[str | None]:
    return _current_row_tenant_id.set(tenant_id)


def get_current_row_tenant_id() -> str:
    tenant_id = _current_row_tenant_id.get()
    if not tenant_id:
        raise RuntimeError("Row strategy requires a tenant context for DB access")
    return tenant_id


def reset_current_row_tenant_id(token: Token[str | None]) -> None:
    _current_row_tenant_id.reset(token)


def _configure_row_session(session: AsyncSession) -> None:
    if session.info.get("_row_strategy_configured"):
        return

    event.listen(session.sync_session, "do_orm_execute", _apply_row_tenant_scope)
    event.listen(session.sync_session, "before_flush", _stamp_row_tenant_writes)
    session.info["_row_strategy_configured"] = True


def _apply_row_tenant_scope(execute_state: object) -> None:
    if not getattr(execute_state, "is_select", False):
        return
    if getattr(execute_state, "is_column_load", False):
        return
    if getattr(execute_state, "is_relationship_load", False):
        return

    tenant_id = get_current_row_tenant_id()
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantAwareModel,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


def _stamp_row_tenant_writes(sync_session: Session, *_: object) -> None:
    tenant_id = get_current_row_tenant_id()

    for instance in sync_session.new:
        if isinstance(instance, TenantAwareModel):
            instance.tenant_id = tenant_id

    for instance in list(sync_session.new) + list(sync_session.dirty):
        if not isinstance(instance, TenantAwareModel):
            continue
        if instance.tenant_id != tenant_id:
            raise ValueError(
                "Row strategy detected a cross-tenant write for "
                f"{instance.__class__.__name__}"
            )


def _create_shared_engine_entry(
    *,
    db_uri: str,
    db_config: DatabaseConfig,
) -> _SharedSchemaEngineEntry:
    engine = create_async_engine(
        db_uri,
        pool_size=db_config.pool_size,
        max_overflow=db_config.max_overflow,
        pool_recycle=db_config.pool_recycle,
        pool_pre_ping=db_config.pool_pre_ping,
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
        pool_size=db_config.pool_size,
        max_overflow=db_config.max_overflow,
        pool_recycle=db_config.pool_recycle,
        pool_pre_ping=db_config.pool_pre_ping,
    )


def _validate_shared_pool_config(
    *,
    entry: _SharedSchemaEngineEntry,
    db_config: DatabaseConfig,
) -> None:
    if (
        entry.pool_size,
        entry.max_overflow,
        entry.pool_recycle,
        entry.pool_pre_ping,
    ) == (
        db_config.pool_size,
        db_config.max_overflow,
        db_config.pool_recycle,
        db_config.pool_pre_ping,
    ):
        return

    raise ValueError(
        "Shared-engine strategy received conflicting pool settings for the "
        f"database URL: {entry.db_uri}"
    )
