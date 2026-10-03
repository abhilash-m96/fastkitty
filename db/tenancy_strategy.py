from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar, Token
from typing import Any, Protocol, Iterable
from dataclasses import dataclass

from fastapi import FastAPI
from sqlalchemy import event, text
from sqlalchemy.orm import with_loader_criteria
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import Settings
from db.session import PoolConfig
from models.base import TenantScopedModel
from schemas.tenancy import DatabaseConfig, TenancyDBStrategy

logger = logging.getLogger(__name__)

# Configurable timeout (seconds) for waiting on idle_event before
# force-disposing an evicted engine. Prevents dispose tasks from blocking forever
# if a request hangs or a session is never closed.
_DISPOSE_IDLE_TIMEOUT: float = 30.0

# Reserved/system schema names that must never be used as tenant schemas,
# even though they pass the identifier regex.
_RESERVED_SCHEMA_NAMES: frozenset[str] = frozenset(
    {
        "public",
        "pg_catalog",
        "information_schema",
        "pg_toast",
        "pg_temp",
        "pg_public",
    }
)


@dataclass(frozen=True, slots=True)
class TenantDBContext:
    """Request-scoped tenant information shared with DB strategies."""

    tenant_id: str
    db_config: DatabaseConfig


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
        self, tenant_db_context: TenantDBContext
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
class _SharedEngineEntry:
    """Shared engine entry used by both schema and row strategies."""

    db_uri: str
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    pool_config: PoolConfig


_current_row_tenant_id: ContextVar[str | None] = ContextVar(
    "current_row_tenant_id", default=None
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
        self, tenant_db_context: TenantDBContext
    ) -> AsyncGenerator[AsyncSession, None]:
        db_config = tenant_db_context.db_config
        entry = await self._acquire_entry(db_config)
        # session creation can fail (e.g. pool exhausted, driver error).
        # _release_entry must run regardless — it decrements active_sessions and
        # potentially sets idle_event, unblocking any pending dispose task.
        # The outer try/finally guarantees _release_entry even if session_factory()
        # or the caller's code raises before yielding.
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
        # collect all engines and pending dispose tasks under the lock,
        # then await everything together so no dispose task races against our
        # direct disposal of the remaining engines.
        async with self._registry_lock:
            entries = list(self._engines.values())
            self._engines.clear()

        pending = list(self._dispose_tasks)
        self._dispose_tasks.clear()

        # Await pending dispose tasks first — they are waiting on idle_event for
        # engines that were already evicted from the registry. Once those settle,
        # dispose the remaining live engines directly.
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        await asyncio.gather(
            *[entry.engine.dispose() for entry in entries],
            return_exceptions=True,
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
        # Guard against hanging requests that never release their session.
        # Without a timeout, an evicted engine's dispose task blocks indefinitely if
        # a session on that engine is stuck (deadlock, slow query, leaked session).
        # After _DISPOSE_IDLE_TIMEOUT seconds we log a warning and force-dispose —
        # accepting that the stuck request will get a connection error rather than
        # silently leaking the engine forever.
        if entry.idle_event is not None:
            try:
                await asyncio.wait_for(
                    entry.idle_event.wait(),
                    timeout=_DISPOSE_IDLE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Timed out waiting for engine %r to become idle before disposal "
                    "(%d active session(s) still in flight). Force-disposing.",
                    entry.db_uri,
                    entry.active_sessions,
                )
        await entry.engine.dispose()


class _SharedEngineTenancyStrategy(TenancyStrategy):
    """
    Base for strategies that share one engine across all tenants.

    Owns engine lifecycle: creation, pool config validation, and disposal.
    Subclasses implement get_session with their own tenant isolation mechanism.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._shared_entry: _SharedEngineEntry | None = None
        self._registry_lock = asyncio.Lock()

    async def setup(self, app: FastAPI) -> None:
        app.state.tenancy_strategy = self

    async def teardown(self) -> None:
        async with self._registry_lock:
            entry = self._shared_entry
            self._shared_entry = None
        if entry is not None:
            await entry.engine.dispose()

    async def _get_or_create_entry(
        self, db_config: DatabaseConfig, *, strategy_name: str
    ) -> _SharedEngineEntry:
        db_uri = db_config.database_uri
        async with self._registry_lock:
            if self._shared_entry is None:
                self._shared_entry = self._create_entry(
                    db_uri=db_uri, db_config=db_config
                )
            else:
                if self._shared_entry.db_uri != db_uri:
                    raise ValueError(
                        f"{strategy_name} strategy requires all tenants to share the "
                        f"same database URL, got: {db_uri}"
                    )
                self._validate_shared_config(
                    entry=self._shared_entry, db_config=db_config
                )
            return self._shared_entry

    def _create_entry(
        self, *, db_uri: str, db_config: DatabaseConfig
    ) -> _SharedEngineEntry:
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
        return _SharedEngineEntry(
            db_uri=db_uri,
            engine=engine,
            session_factory=session_factory,
            pool_config=pool_config,
        )

    def _validate_shared_config(
        self,
        *,
        entry: _SharedEngineEntry,
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
                f"{self.strategy_name} strategy received conflicting pool settings "
                f"for the shared database URL: {entry.db_uri}"
            )


class SchemaTenancyStrategy(_SharedEngineTenancyStrategy):
    strategy_name: TenancyDBStrategy = "schema"

    @asynccontextmanager
    async def get_session(
        self, tenant_db_context: TenantDBContext
    ) -> AsyncGenerator[AsyncSession, None]:
        db_config = tenant_db_context.db_config
        # _normalize_schema_name now also rejects reserved PostgreSQL
        # schema names (public, pg_catalog, information_schema, etc.) that pass
        # the identifier regex but would silently redirect queries to the wrong
        # namespace or expose system tables.
        schema_name = _normalize_schema_name(db_config)
        entry = await self._get_or_create_entry(db_config, strategy_name="Schema")
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


class RowTenancyStrategy(_SharedEngineTenancyStrategy):
    """
    Row-level tenant isolation via ORM event hooks.

    IMPORTANT — ORM bypass:
    Isolation is enforced only for ORM-level queries routed through SQLAlchemy's
    do_orm_execute event. The following patterns bypass the tenant filter entirely
    and must NOT be used against tenant-scoped tables:

        # These bypass the tenant filter — do not use on TenantScopedModel tables:
        await session.execute(text("SELECT * FROM posts"))
        await session.execute(update(Post).values(title="..."))

    For ad-hoc queries, always include an explicit WHERE tenant_id = :tid clause
    and bind the value from get_current_row_tenant_id().
    """

    strategy_name: TenancyDBStrategy = "row"

    @asynccontextmanager
    async def get_session(
        self, tenant_db_context: TenantDBContext
    ) -> AsyncGenerator[AsyncSession, None]:
        db_config = tenant_db_context.db_config
        entry = await self._get_or_create_entry(db_config, strategy_name="Row")
        session = entry.session_factory()
        _configure_row_session(session)
        token = set_current_row_tenant_id(tenant_db_context.tenant_id)
        session.info["tenant_id"] = tenant_db_context.tenant_id
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            reset_current_row_tenant_id(token)
            await session.close()


def create_tenancy_strategy(settings: Settings) -> TenancyStrategy:
    """Instantiate the configured tenancy strategy once at startup.

    Each branch returns early — the if/if/if pattern (rather than if/elif/elif)
    is intentional: it avoids implying that the branches are mutually exclusive
    in a way that would matter, and each return makes the flow unambiguous.
    The final raise is unreachable in production (Pydantic validates
    TENANCY_DB_STRATEGY at startup) but guards against test code that
    constructs Settings directly with an invalid value.
    """
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
    """Validate and return the tenant schema name safe for interpolation into SET search_path.

    Two-stage guard:
    1. Regex: ensures the name is a valid SQL identifier (prevents injection).
    2. Reserved-name check: rejects names that are valid identifiers but refer to
       PostgreSQL system schemas (public, pg_catalog, information_schema, etc.).
       A tenant named 'public' would pass the regex but silently redirect all
       queries to the shared public schema — a cross-tenant data exposure risk.
    """
    schema_name = db_config.schema_name
    if not schema_name:
        raise ValueError("Schema strategy requires database_config.schema_name")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema_name):
        raise ValueError(f"Invalid schema_name for schema strategy: {schema_name!r}")
    # Issue #1: block reserved/system schema names even though they pass the regex.
    if schema_name.lower() in _RESERVED_SCHEMA_NAMES:
        raise ValueError(
            f"schema_name {schema_name!r} is a reserved PostgreSQL schema name "
            "and cannot be used as a tenant schema."
        )
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
    # Guard against double-registration: session.info persists for the lifetime
    # of the session object, so if the same session is somehow reused (e.g. via
    # connection reuse), events won't be registered twice. In practice this
    # shouldn't happen given expire_on_commit=False and explicit session.close(),
    # but the flag makes it unconditionally safe.
    if session.info.get("_row_strategy_configured"):
        return
    event.listen(session.sync_session, "do_orm_execute", _apply_row_tenant_scope)
    event.listen(session.sync_session, "before_flush", _stamp_row_tenant_writes)
    session.info["_row_strategy_configured"] = True


class _ExecuteState(Protocol):
    is_select: bool
    is_column_load: bool
    is_relationship_load: bool
    statement: Any


def _apply_row_tenant_scope(execute_state: _ExecuteState) -> None:
    if not execute_state.is_select:
        return
    if execute_state.is_column_load:
        return
    if execute_state.is_relationship_load:
        return

    tenant_id = get_current_row_tenant_id()
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantScopedModel,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


class _SyncSessionLike(Protocol):
    new: Iterable[object]
    dirty: Iterable[object]


def _stamp_row_tenant_writes(sync_session: _SyncSessionLike, *_: object) -> None:
    tenant_id = get_current_row_tenant_id()

    for instance in sync_session.new:
        if isinstance(instance, TenantScopedModel):
            instance.tenant_id = tenant_id

    for instance in sync_session.dirty:
        if not isinstance(instance, TenantScopedModel):
            continue
        if instance.tenant_id != tenant_id:
            raise ValueError(
                "Row strategy detected a cross-tenant write for "
                f"{instance.__class__.__name__}"
            )
