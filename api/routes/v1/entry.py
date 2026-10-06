from fastapi import APIRouter
from api.routes.v1.health import router as health_router
from api.routes.v1.hello import router as hello_router
from api.routes.v1.blog_posts import router as posts_router


v1_router = APIRouter(prefix="/v1")
v1_router.include_router(health_router)
v1_router.include_router(hello_router)
v1_router.include_router(posts_router)

