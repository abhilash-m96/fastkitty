from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base, TenantScopedModel, TimestampedModel


class BlogPost(TenantScopedModel, TimestampedModel, Base):
    __tablename__ = "blog_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(100), nullable=False)
