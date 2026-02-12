from sqlalchemy import Column, Integer, String, Text, DateTime, func
from models.base import Base


class BlogPost(Base):
    __tablename__ = "blog_posts"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=False)

    # Explicitly store timestamps in UTC at database level for consistency across all inserts (ORM or raw SQL)
    # DateTime(timezone=True) makes it timezone-aware; func.timezone('UTC', func.now()) forces UTC storage
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.timezone("UTC", func.now()),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.timezone("UTC", func.now()),
        onupdate=func.timezone("UTC", func.now()),
    )
