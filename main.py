from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes.v1.entry import v1_router as v1_router
from config.settings import get_settings
from config.telemetry import setup_telemetry
from config.tenancy_strategy_validation import validate_tenancy_strategy_startup
from db.session import close_all_engines
from db.tenancy_strategy import create_tenancy_strategy

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_tenancy_strategy_startup(settings)
    tenancy_strategy = create_tenancy_strategy(settings)
    await tenancy_strategy.setup(app)
    try:
        yield
    finally:
        await tenancy_strategy.teardown()
        await (
            close_all_engines()
        )  # closes shared/foundation engines; database strategy owns its own


app = FastAPI(
    title=settings.APP_NAME,
    description=settings.DESCRIPTION,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url=None if settings.ENV.lower() != "dev" else "/docs",
    redoc_url=None if settings.ENV.lower() != "dev" else "/redoc",
    openapi_url=None if settings.ENV.lower() != "dev" else "/openapi.json",
)

setup_telemetry(app, settings)

app.include_router(v1_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
