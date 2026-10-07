from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class BlogPostCreate(BaseModel):
    title: str = Field(..., max_length=200, min_length=1)
    content: str = Field(..., min_length=1, max_length=50_000)


class BlogPostUpdate(BaseModel):
    title: str | None = Field(None, max_length=200, min_length=1)
    content: str | None = Field(None, min_length=1, max_length=50_000)


class BlogPostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    author: str
    created_at: datetime
    updated_at: datetime
