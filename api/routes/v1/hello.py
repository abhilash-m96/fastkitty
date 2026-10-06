from fastapi import APIRouter, Depends
from api.deps.tenancy import (
    get_feature_config,
    get_tenant_config,
    require_active_tenant,
)
from schemas.tenancy import FeatureConfig, TenantConfig


router = APIRouter(
    tags=["Greet"],
    dependencies=[Depends(require_active_tenant)],
)


@router.get("/hello", name="greet")
async def hello(
    tenant_config: TenantConfig = Depends(get_tenant_config),
    feature_config: FeatureConfig | None = Depends(get_feature_config("greet")),
):
    message = feature_config.get("message") if feature_config else None
    tenant_name = tenant_config.display_name
    if not message:
        message = f"Hello {tenant_name}!"
    if "{tenant_name}" in message:
        message = message.replace("{tenant_name}", tenant_config.display_name)

    return {"message": message}
