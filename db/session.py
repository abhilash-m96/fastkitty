from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@dataclass(frozen=True)
class PoolConfig:
    db_uri: str
    pool_size: int
    max_overflow: int
    pool_recycle: int
    pool_pre_ping: bool


# TODO: replace with bounded LRU registry in feat/database-strategy
_engines: dict[PoolConfig, AsyncEngine] = {}
_session_factories: dict[PoolConfig, async_sessionmaker[AsyncSession]] = {}


def get_engine(config: PoolConfig) -> AsyncEngine:
    """
    Create and cache an async database engine.

    Caches by full pool config. Same URI with different pool settings
    produces separate engines.
    """
    if config not in _engines:
        _engines[config] = create_async_engine(
            config.db_uri,
            pool_size=config.pool_size,
            max_overflow=config.max_overflow,
            pool_recycle=config.pool_recycle,
            pool_pre_ping=config.pool_pre_ping,
            echo=False,
        )
    return _engines[config]


def get_session_factory(config: PoolConfig) -> async_sessionmaker[AsyncSession]:
    if config not in _session_factories:
        engine = get_engine(config)
        _session_factories[config] = async_sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_factories[config]


@asynccontextmanager
async def create_session(config: PoolConfig) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a request-scoped async session.

    Rolls back on exception, always closes on exit.
    """
    factory = get_session_factory(config)
    session = factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def close_all_engines() -> None:
    """Dispose all cached engines. Call during app shutdown."""
    cached_engines = list(_engines.values())
    _session_factories.clear()
    _engines.clear()
    for engine in cached_engines:
        await engine.dispose()
