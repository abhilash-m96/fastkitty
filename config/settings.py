from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
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
    TENANT_SECRET_PROVIDER: str = Field(default="file")
    TENANT_SECRET_FILE_PATH: str = Field(default="tenants_secrets.json")
    AWS_ACCESS_KEY_ID: str | None = Field(default=None)
    AWS_SECRET_ACCESS_KEY: str | None = Field(default=None)
    AWS_REGION: str | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_provider_settings(self) -> "Settings":
        config_provider = self.TENANCY_CONFIG_PROVIDER.lower()
        secret_provider = self.TENANT_SECRET_PROVIDER.lower()

        if config_provider == "file" and not self.TENANT_CONFIG_FILE_PATH:
            raise ValueError("TENANT_CONFIG_FILE_PATH is required for file config provider")

        if secret_provider == "file" and not self.TENANT_SECRET_FILE_PATH:
            raise ValueError("TENANT_SECRET_FILE_PATH is required for file secret provider")

        if secret_provider == "aws":
            if not self.AWS_ACCESS_KEY_ID or not self.AWS_SECRET_ACCESS_KEY:
                raise ValueError(
                    "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required for aws secret provider"
                )

        return self


@lru_cache()
def get_settings() -> Settings:
    return Settings()
