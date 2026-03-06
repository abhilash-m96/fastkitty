from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, BaseModel, model_validator
from functools import lru_cache


class FileConnectionData(BaseModel):
    file_path: str = Field(..., description="Path to the JSON configuration file")


class AWSConnectionData(BaseModel):
    access_key_id: str = Field(..., description="AWS access key id")
    secret_access_key: str = Field(..., description="AWS secret access key")
    region: str | None = Field(default=None, description="AWS region")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="_", env_nested_max_split=1)
    # App Settings
    APP_NAME: str = Field(default="multi-tenant-app")
    DESCRIPTION: str = Field(default="Multi-Tenant Application Example")
    DEBUG: bool = Field(default=True)
    VERSION: str = Field(default="0.1.0")
    ENV: str = Field(default="dev")

    TENANCY_CONFIG_PROVIDER: str = Field(default="file")
    TENANT_CONFIG_FILE_PATH: str = Field(default="tenants_config.json")
    TENANT_SECRET_FILE_PATH: str = Field(default="tenants_secrets.json")
    TENANT_SECRET_PROVIDER: str = Field(default="file")

    AWS_ACCESS_KEY_ID: str | None = Field(default=None)
    AWS_SECRET_ACCESS_KEY: str | None = Field(default=None)
    AWS_REGION: str | None = Field(default=None)

    USER_DATA_PROVIDER: str = Field(default="header")
    USER_ID_HEADER_NAME: str = Field(default="X-User-Id")
    JWT_VALIDATE: bool = Field(default=False)
    JWT_SECRET: str | None = Field(default=None)
    JWT_ALGORITHM: str = Field(default="HS256")

    @model_validator(mode="after")
    def _validate_provider_config(self) -> "Settings":
        tenant_config_provider = self.TENANCY_CONFIG_PROVIDER.lower()
        tenant_secret_provider = self.TENANT_SECRET_PROVIDER.lower()

        if tenant_config_provider == "file" and not self.TENANT_CONFIG_FILE_PATH:
            raise ValueError("TENANT_CONFIG_FILE_PATH is required for file config provider")

        if tenant_secret_provider == "file" and not self.TENANT_SECRET_FILE_PATH:
            raise ValueError("TENANT_SECRET_FILE_PATH is required for file secret provider")

        if tenant_secret_provider == "aws":
            if not self.AWS_ACCESS_KEY_ID or not self.AWS_SECRET_ACCESS_KEY:
                raise ValueError(
                    "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required for aws secret provider"
                )

        return self

@lru_cache()
def get_settings() -> Settings:
    return Settings()
