from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = Field(default="multi-tenant-app")
    DESCRIPTION: str = Field(default="Multi-Tenant Application Example")
    DEBUG: bool = Field(default=True)
    VERSION: str = Field(default="0.1.0")
    ENV: str = Field(default="dev")
    TENANCY_CONFIG_PROVIDER: str = Field(default="file")
    TENANT_CONFIG_FILE_PATH: str = Field(default="tenants_config.json")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
