from fastapi import APIRouter
from api.routes.v1.hello import router as hello_router


v1_router = APIRouter(prefix="/v1")
v1_router.include_router(hello_router)
