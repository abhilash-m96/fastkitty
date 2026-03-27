from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Response, status

from api.deps.db import get_blog_posts_service
from api.deps.tenancy import require_active_tenant
from api.deps.user_data import get_user_data
from schemas.posts import BlogPostCreate, BlogPostResponse, BlogPostUpdate
from services.blog_posts_service import BlogPostsService


router = APIRouter(
    tags=["Blog-Posts"],
    dependencies=[Depends(require_active_tenant)],
)


@router.post(
    "/blog-posts",
    status_code=status.HTTP_201_CREATED,
    response_model=BlogPostResponse,
    summary="Create blog post",
    description="Create a new blog post for the current user",
    responses={
        status.HTTP_201_CREATED: {"description": "Blog post created successfully"},
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid request payload"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"description": "Server error"},
    },
)
def create_blog_post(
    payload: Annotated[BlogPostCreate, Body()],
    service: BlogPostsService = Depends(get_blog_posts_service),
    user_data: dict = Depends(get_user_data),
) -> BlogPostResponse:
    blog_post = service.create_post(payload, user_id=user_data["user_id"])
    return BlogPostResponse.model_validate(blog_post)


@router.get(
    "/blog-posts",
    response_model=list[BlogPostResponse],
    summary="List user's blog posts",
    description="List all blog posts for the current user",
    responses={
        status.HTTP_200_OK: {"description": "Blog posts retrieved successfully"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"description": "Server error"},
    },
)
def list_blog_posts(
    service: BlogPostsService = Depends(get_blog_posts_service),
    user_data: dict = Depends(get_user_data),
) -> list[BlogPostResponse]:
    posts = service.list_posts(user_id=user_data["user_id"])
    return [BlogPostResponse.model_validate(p) for p in posts]


@router.get(
    "/blog-posts/{blog_post_id}",
    response_model=BlogPostResponse,
    summary="Get blog post",
    description="Retrieve a single blog post by it's id and user_id",
    responses={
        status.HTTP_200_OK: {"description": "Blog Post retrieved successfully"},
        status.HTTP_404_NOT_FOUND: {"description": "Blog Post not found"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"description": "Server error"},
    },
)
def get_blog_post(
    blog_post_id: Annotated[int, Path(ge=1)],
    service: BlogPostsService = Depends(get_blog_posts_service),
    user_data: dict = Depends(get_user_data),
) -> BlogPostResponse:
    blog_post = service.get_post(blog_post_id, user_id=user_data["user_id"])
    if not blog_post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Blog Post not found"
        )
    return BlogPostResponse.model_validate(blog_post)


@router.patch(
    "/blog-posts/{blog_post_id}",
    response_model=BlogPostResponse,
    summary="Update blog post",
    description="Partially update a blog post by id",
    responses={
        status.HTTP_200_OK: {"description": "Blog Post updated successfully"},
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid request payload"},
        status.HTTP_404_NOT_FOUND: {"description": "Blog Post not found"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"description": "Server error"},
    },
)
def update_blog_post(
    blog_post_id: Annotated[int, Path(ge=1)],
    payload: Annotated[BlogPostUpdate, Body()],
    service: BlogPostsService = Depends(get_blog_posts_service),
    user_data: dict = Depends(get_user_data),
) -> BlogPostResponse:
    blog_post = service.get_post(blog_post_id, user_id=user_data["user_id"])
    if not blog_post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Blog Post not found"
        )
    updated_blog_post = service.update_post(blog_post, payload)
    return BlogPostResponse.model_validate(updated_blog_post)


@router.delete(
    "/blog-posts/{blog_post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete blog post",
    description="Delete a blog post by id",
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "Blog post deleted successfully"},
        status.HTTP_404_NOT_FOUND: {"description": "Blog post not found"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"description": "Server error"},
    },
)
def delete_blog_post(
    blog_post_id: Annotated[int, Path(ge=1)],
    service: BlogPostsService = Depends(get_blog_posts_service),
    user_data: dict = Depends(get_user_data),
) -> Response:
    blog_post = service.get_post(blog_post_id, user_id=user_data["user_id"])
    if not blog_post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Blog Post not found"
        )
    service.delete_post(blog_post)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
