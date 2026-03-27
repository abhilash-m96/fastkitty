from sqlalchemy import Column, Integer, String, Text
from models.base import Base, TenantAwareModel


class BlogPost(TenantAwareModel, Base):
    __tablename__ = "blog_posts"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=False)
