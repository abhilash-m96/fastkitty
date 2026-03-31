from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import create_session, PoolConfig
from schemas.tenancy import TenantSecrets
from services.blog_posts_service import BlogPostsService
from api.deps.tenancy import get_tenant_secrets


async def get_db(
    tenant_secrets: TenantSecrets = Depends(get_tenant_secrets),
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async DB session for the current tenant."""
    db_config = tenant_secrets.database_config
    config = PoolConfig(
        db_uri=db_config.database_uri,
        pool_size=db_config.pool_size,
        max_overflow=db_config.max_overflow,
        pool_recycle=db_config.pool_recycle,
        pool_pre_ping=db_config.pool_pre_ping,
    )
    async with create_session(config) as session:
        yield session


def get_blog_posts_service(db: AsyncSession = Depends(get_db)) -> BlogPostsService:
    return BlogPostsService(db)
