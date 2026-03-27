from sqlalchemy.orm import Session

from models.posts import BlogPost
from schemas.posts import BlogPostCreate, BlogPostUpdate


class BlogPostsService:
    def __init__(self, db: Session):
        self.db = db

    def list_posts(self, *, user_id: str) -> list[BlogPost]:
        return (
            self.db.query(BlogPost)
            .filter(BlogPost.author == user_id)
            .order_by(BlogPost.created_at.desc())
            .all()
        )

    def get_post(self, post_id: int, *, user_id: str) -> BlogPost | None:
        return (
            self.db.query(BlogPost)
            .filter(BlogPost.id == post_id, BlogPost.author == user_id)
            .first()
        )

    def create_post(self, payload: BlogPostCreate, *, user_id: str) -> BlogPost:
        post = BlogPost(title=payload.title, content=payload.content, author=user_id)
        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)
        return post

    def update_post(self, post: BlogPost, payload: BlogPostUpdate) -> BlogPost:
        update_data = payload.model_dump(exclude_unset=True)
        update_data.pop("author", None)
        for field, value in update_data.items():
            setattr(post, field, value)
        self.db.commit()
        self.db.refresh(post)
        return post

    def delete_post(self, post: BlogPost) -> None:
        self.db.delete(post)
        self.db.commit()
