from fastapi import FastAPI
from config.settings import get_settings
from api.routes.v1.entry import v1_router as v1_router

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    description=settings.DESCRIPTION,
    version=settings.VERSION,
    docs_url=None if settings.ENV.lower() != "dev" else "/docs",
    redoc_url=None if settings.ENV.lower() != "dev" else "/redoc",
    openapi_url=None if settings.ENV.lower() != "dev" else "/openapi.json",
)

app.include_router(v1_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
