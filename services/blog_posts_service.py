from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.posts import BlogPost
from schemas.posts import BlogPostCreate, BlogPostUpdate


class BlogPostsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_posts(self, *, user_id: str) -> list[BlogPost]:
        result = await self.db.scalars(
            select(BlogPost)
            .where(BlogPost.author == user_id)
            .order_by(BlogPost.created_at.desc())
        )
        return list(result)

    async def get_post(self, post_id: int, *, user_id: str) -> BlogPost | None:
        result = await self.db.scalar(
            select(BlogPost).where(
                BlogPost.id == post_id,
                BlogPost.author == user_id,
            )
        )
        return result

    async def create_post(self, payload: BlogPostCreate, *, user_id: str) -> BlogPost:
        post = BlogPost(title=payload.title, content=payload.content, author=user_id)
        self.db.add(post)
        await self.db.commit()
        await self.db.refresh(post)
        return post

    async def update_post(self, post: BlogPost, payload: BlogPostUpdate) -> BlogPost:
        update_data = payload.model_dump(exclude_unset=True)
        update_data.pop("author", None)
        for field, value in update_data.items():
            setattr(post, field, value)
        await self.db.commit()
        await self.db.refresh(post)
        return post

    async def delete_post(self, post: BlogPost) -> None:
        await self.db.delete(post)
        await self.db.commit()
