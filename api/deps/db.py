from typing import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.tenancy_strategy import (
    TenancyStrategy,
    get_app_tenancy_strategy,
)
from services.blog_posts_service import BlogPostsService
from api.deps.tenancy import get_tenant_db_context
from db.tenancy_strategy import TenantDBContext


async def get_db(
    request: Request,
    tenant_db_context: TenantDBContext = Depends(get_tenant_db_context),
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped DB session via the active tenancy strategy."""
    strategy: TenancyStrategy = get_app_tenancy_strategy(request.app)
    async with strategy.get_session(tenant_db_context) as session:
        yield session


def get_blog_posts_service(db: AsyncSession = Depends(get_db)) -> BlogPostsService:
    return BlogPostsService(db)
