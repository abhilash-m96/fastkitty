from typing import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.tenancy_strategy import (
    TenantContext,
    TenancyStrategy,
    get_app_tenancy_strategy,
)
from schemas.tenancy import DatabaseConfig
from services.blog_posts_service import BlogPostsService
from api.deps.tenancy import get_tenant_context


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
    request: Request,
    tenant_context: TenantContext = Depends(get_tenant_context),
) -> AsyncGenerator[AsyncSession, None]:
    """Get a database session for the current tenant."""

    strategy: TenancyStrategy = get_app_tenancy_strategy(request.app)
    async for session in strategy.get_session(tenant_context):
        yield session


def get_blog_posts_service(db: AsyncSession = Depends(get_db)) -> BlogPostsService:
    return BlogPostsService(db)
