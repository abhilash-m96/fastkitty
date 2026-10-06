from datetime import datetime, timezone
import logging
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.posts import BlogPost
from schemas.posts import BlogPostCreate, BlogPostUpdate
from schemas.tenancy import FeatureConfig

logger = logging.getLogger(__name__)


class BlogPostsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_posts(self, *, user_id: str) -> list[BlogPost]:
        logger.debug("Listing blog posts for author '%s'", user_id)
        result = await self.db.scalars(
            select(BlogPost)
            .where(BlogPost.author == user_id)
            .order_by(BlogPost.created_at.desc())
        )
        return list(result)

    async def get_post(self, post_id: int, *, user_id: str) -> BlogPost | None:
        logger.debug("Fetching blog post id=%s for author '%s'", post_id, user_id)
        result = await self.db.scalar(
            select(BlogPost).where(
                BlogPost.id == post_id,
                BlogPost.author == user_id,
            )
        )
        return result

    async def create_post(
        self,
        payload: BlogPostCreate,
        user_id: str,
        feature_config: FeatureConfig | None = None,
    ) -> BlogPost:
        logger.info("Creating blog post for author '%s'", user_id)

        max_daily_posts = (
            feature_config.get("max_daily_posts") if feature_config else None
        )
        if max_daily_posts is not None:
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            count_query = (
                select(func.count())
                .select_from(BlogPost)
                .where(BlogPost.created_at >= today_start)
            )
            posts_today = await self.db.scalar(count_query) or 0
            if posts_today >= max_daily_posts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Daily posting limit of {max_daily_posts} reached for this tenant.",
                )

        post = BlogPost(title=payload.title, content=payload.content, author=user_id)
        self.db.add(post)
        await self.db.commit()
        await self.db.refresh(post)
        logger.info("Created blog post id=%s for author '%s'", post.id, user_id)
        return post

    async def update_post(self, post: BlogPost, payload: BlogPostUpdate) -> BlogPost:
        logger.info("Updating blog post id=%s", post.id)
        update_data = payload.model_dump(exclude_unset=True)
        update_data.pop("author", None)
        for field, value in update_data.items():
            setattr(post, field, value)
        await self.db.commit()
        await self.db.refresh(post)
        return post

    async def delete_post(self, post: BlogPost) -> None:
        logger.info("Deleting blog post id=%s", post.id)
        await self.db.delete(post)
        await self.db.commit()
