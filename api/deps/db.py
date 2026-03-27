from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import create_session
from schemas.tenancy import TenantSecrets, DatabaseConfig
from services.blog_posts_service import BlogPostsService
from api.deps.tenancy import get_tenant_secrets


def build_db_uri(db_config: DatabaseConfig) -> str:
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


async def get_db(
    tenant_secrets: TenantSecrets = Depends(get_tenant_secrets),
) -> AsyncGenerator[AsyncSession, None]:
    """Get a database session for the current tenant."""

    db_config = tenant_secrets.database_config
    async for session in create_session(
        db_uri=build_db_uri(db_config),
        pool_size=tenant_secrets.database_config.pool_size,
        max_overflow=tenant_secrets.database_config.max_overflow,
        pool_recycle=tenant_secrets.database_config.pool_recycle,
        pool_pre_ping=tenant_secrets.database_config.pool_pre_ping,
    ):
        yield session


def get_blog_posts_service(db: AsyncSession = Depends(get_db)) -> BlogPostsService:
    return BlogPostsService(db)
