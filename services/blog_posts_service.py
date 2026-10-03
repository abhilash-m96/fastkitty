import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.posts import BlogPost
from schemas.posts import BlogPostCreate, BlogPostUpdate

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

    async def create_post(self, payload: BlogPostCreate, *, user_id: str) -> BlogPost:
        logger.info("Creating blog post '%s' for author '%s'", payload.title, user_id)
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
