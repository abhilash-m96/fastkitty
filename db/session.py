from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

EngineCacheKey = tuple[str, int, int, int, bool]
_engines: dict[EngineCacheKey, AsyncEngine] = {}
_session_factories: dict[EngineCacheKey, async_sessionmaker[AsyncSession]] = {}


def _cache_key(
    db_uri: str,
    pool_size: int,
    max_overflow: int,
    pool_recycle: int,
    pool_pre_ping: bool,
) -> EngineCacheKey:
    return (db_uri, pool_size, max_overflow, pool_recycle, pool_pre_ping)


def get_engine(
    db_uri: str,
    pool_size: int,
    max_overflow: int,
    pool_recycle: int,
    pool_pre_ping: bool,
) -> AsyncEngine:
    """
    Create and cache a database engine.

    Caches based on both URI and pool configuration. If the same URI
    is requested with different pool settings, separate engines are created.

    Args:
        db_uri: Database connection URI
        pool_size: Minimum number of connections in pool
        max_overflow: Additional connections under load
        pool_recycle: Recycle connections after N seconds
        pool_pre_ping: Verify connections before use

    Returns:
        Cached SQLAlchemy Engine instance
    """
    cache_key = _cache_key(
        db_uri, pool_size, max_overflow, pool_recycle, pool_pre_ping
    )
    if cache_key not in _engines:
        _engines[cache_key] = create_async_engine(
            db_uri,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=pool_recycle,
            pool_pre_ping=pool_pre_ping,
            echo=False,
        )
    return _engines[cache_key]


def get_session_factory(
    db_uri: str,
    pool_size: int,
    max_overflow: int,
    pool_recycle: int,
    pool_pre_ping: bool,
) -> async_sessionmaker[AsyncSession]:
    cache_key = _cache_key(
        db_uri, pool_size, max_overflow, pool_recycle, pool_pre_ping
    )
    if cache_key not in _session_factories:
        engine = get_engine(
            db_uri=db_uri,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=pool_recycle,
            pool_pre_ping=pool_pre_ping,
        )
        _session_factories[cache_key] = async_sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_factories[cache_key]


async def create_session(
    db_uri: str,
    pool_size: int,
    max_overflow: int,
    pool_recycle: int,
    pool_pre_ping: bool,
) -> AsyncGenerator[AsyncSession, None]:
    session_factory = get_session_factory(
        db_uri=db_uri,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_pre_ping=pool_pre_ping,
    )
    session = session_factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def close_all_engines() -> None:
    cached_engines = list(_engines.values())
    _session_factories.clear()
    _engines.clear()
    for engine in cached_engines:
        await engine.dispose()
