from typing import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from db.session import create_session
from schemas.tenancy import TenantSecrets, DatabaseConfig
from services.blog_posts_service import BlogPostsService
from api.deps.tenancy import get_tenant_secrets


def build_db_uri(db_config: DatabaseConfig) -> str:
    return db_config.database_uri or (
        f"{db_config.dialect}://{db_config.username}:{db_config.password}"
        f"@{db_config.host}:{db_config.port}/{db_config.database_name}"
    )


def get_db(
    tenant_secrets: TenantSecrets = Depends(get_tenant_secrets),
) -> Generator[Session, None, None]:
    """Get a database session for the current tenant."""

    db_config = tenant_secrets.database_config
    yield from create_session(
        db_uri=build_db_uri(db_config),
        pool_size=tenant_secrets.database_config.pool_size,
        max_overflow=tenant_secrets.database_config.max_overflow,
        pool_recycle=tenant_secrets.database_config.pool_recycle,
        pool_pre_ping=tenant_secrets.database_config.pool_pre_ping,
    )


def get_blog_posts_service(db: Session = Depends(get_db)) -> BlogPostsService:
    return BlogPostsService(db)
