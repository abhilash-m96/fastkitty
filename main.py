from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes.v1.entry import v1_router as v1_router
from config.settings import get_settings
from db.session import close_all_engines

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        yield
    finally:
        await close_all_engines()


app = FastAPI(
    title=settings.APP_NAME,
    description=settings.DESCRIPTION,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url=None if settings.ENV.lower() != "dev" else "/docs",
    redoc_url=None if settings.ENV.lower() != "dev" else "/redoc",
    openapi_url=None if settings.ENV.lower() != "dev" else "/openapi.json",
)

app.include_router(v1_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
