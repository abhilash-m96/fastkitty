from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Health Check", include_in_schema=True)
async def health_check() -> dict[str, str]:
    """Public health check endpoint for container probes and load balancers."""
    return {"status": "ok"}
