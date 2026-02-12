from contextlib import contextmanager
from functools import lru_cache
from sqlalchemy.engine import Engine
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator


@lru_cache(maxsize=100)
def get_engine(
    db_uri: str,
    pool_size: int,
    max_overflow: int,
    pool_recycle: int,
    pool_pre_ping: bool
) -> Engine:
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
    return create_engine(
        db_uri,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_pre_ping=pool_pre_ping,
        echo=False
    )


def create_session(
    db_uri: str,
    pool_size: int,
    max_overflow: int,
    pool_recycle: int,
    pool_pre_ping: bool
) -> Generator[Session, None, None]:
    """
    Create a database session for a single request.

    Args:
        db_uri: Database connection URI
        pool_size: Minimum connections in pool
        max_overflow: Additional connections under load
        pool_recycle: Recycle connections after N seconds
        pool_pre_ping: Verify connections before use

    Yields:
        SQLAlchemy Session instance
    """
    engine = get_engine(
        db_uri=db_uri,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_pre_ping=pool_pre_ping
    )

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    try:
        yield session
    finally:
        session.close()
