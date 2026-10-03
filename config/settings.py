from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel, Field, field_validator
import json
from typing import Annotated, ClassVar, Literal, Union

from schemas.tenancy import DatabaseConfig, TenancyDBStrategy
from schemas.user_data import UserDataField


class TenancyConfigFileConnection(BaseModel):
    type: Literal["file"] = "file"
    file_path: str = Field(default="tenants_config.json")


class TenancyConfigDBConnection(DatabaseConfig):
    type: Literal["db"] = "db"


class HCConsulTenancyConfigConnection(BaseModel):
    type: Literal["hc_consul"] = "hc_consul"
    url: str
    token: str | None = Field(default=None)
    consul_prefix: str = Field(default="tenants/config/")


TenancyConfigConnection = Annotated[
    Union[
        TenancyConfigFileConnection,
        TenancyConfigDBConnection,
        HCConsulTenancyConfigConnection,
    ],  # New providers to be added here
    Field(discriminator="type"),
]


class TenancySecretsFileConnection(BaseModel):
    type: Literal["file"] = "file"
    file_path: str = Field(default="tenants_secrets.json")


class TenancySecretsGCPConnection(BaseModel):
    type: Literal["gcp"] = "gcp"
    project_id: str
    secret_id: str
    version: str = Field(default="latest")
    service_account_key_path: str | None = Field(default=None)


class HCVaultTenancySecretsConnection(BaseModel):
    type: Literal["hc_vault"] = "hc_vault"
    url: str
    token: str
    vault_kv_path: str = Field(default="secret/data/tenants/{tenant_id}")


TenancySecretsConnection = Annotated[
    Union[
        TenancySecretsFileConnection,
        TenancySecretsGCPConnection,
        HCVaultTenancySecretsConnection,
    ],  # New providers to be added here
    Field(discriminator="type"),
]


class UserDataHeaderSource(BaseModel):
    type: Literal["header"] = "header"
    user_id_header: str = Field(default="X-User-ID")
    user_email_header: str | None = Field(default="X-User-Email")
    user_roles_header: str | None = Field(default="X-User-Roles")
    roles_delimiter: str = Field(default=",")  # "admin,editor" → ["admin", "editor"]

    _payload_key_map: ClassVar[dict[str, UserDataField]] = {
        "user_id_header": UserDataField.user_id,
        "user_email_header": UserDataField.email,
        "user_roles_header": UserDataField.roles,
    }


class UserDataJWTSource(BaseModel):
    type: Literal["jwt"] = "jwt"
    header_name: str = Field(default="Authorization")
    prefix: str | None = Field(default="Bearer")

    # No secret here — gateway already verified, we just decode
    user_id_claim: str = Field(default="sub")
    user_email_claim: str | None = Field(default="email")
    user_roles_claim: str | None = Field(default="roles")

    _payload_key_map: ClassVar[dict[str, UserDataField]] = {
        "user_id_claim": UserDataField.user_id,
        "user_email_claim": UserDataField.email,
        "user_roles_claim": UserDataField.roles,
    }


class UserDataSingleHeaderClaimsSource(BaseModel):
    type: Literal["claims"] = "claims"
    header_name: str = Field(default="X-User-Claims")
    user_id_field: str = Field(default="id")
    user_email_field: str | None = Field(default="email")
    user_roles_field: str | None = Field(default="roles")

    _payload_key_map: ClassVar[dict[str, UserDataField]] = {
        "user_id_field": UserDataField.user_id,
        "user_email_field": UserDataField.email,
        "user_roles_field": UserDataField.roles,
    }


UserDataSource = Annotated[
    Union[
        UserDataHeaderSource,
        UserDataJWTSource,
        UserDataSingleHeaderClaimsSource,
    ],
    Field(discriminator="type"),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="allow"
    )

    # App Settings
    APP_NAME: str = Field(default="fastkitty")
    DESCRIPTION: str = Field(default="fastkitty multi-tenant service template")
    DEBUG: bool = Field(default=True)
    VERSION: str = Field(default="0.1.0")
    ENV: str = Field(default="dev")

    # Tenancy Settings
    TENANCY_CONFIG_CONNECTION: TenancyConfigConnection = Field(
        default=TenancyConfigFileConnection()
    )

    TENANCY_SECRETS_CONNECTION: TenancySecretsConnection = Field(
        default=TenancySecretsFileConnection()
    )

    TENANCY_DB_STRATEGY: TenancyDBStrategy = Field(
        default="database",
        description="Database multi-tenancy strategy selected at startup",
    )
    TENANCY_DATABASE_MAX_ENGINES: int = Field(
        default=50,
        description="Maximum number of cached tenant database engines in database mode",
        ge=1,
        le=500,
    )

    # User data provider
    USER_DATA_SOURCE: UserDataSource | None = Field(
        default=None,
        description="User data extraction strategy (headers | jwt | single header claims). "
        "Omit entirely if the service does not require user identity extraction.",
    )

    # Logfire / Telemetry Settings
    LOGFIRE_ENABLED: bool = Field(
        default=True,
        description="Enable or disable Logfire telemetry instrumentations",
    )
    LOGFIRE_SEND_TO_LOGFIRE: bool = Field(
        default=False,
        description="Whether to export spans to Logfire cloud servers. Defaults to False (local console mode only).",
    )
    LOGFIRE_TOKEN: str | None = Field(
        default=None,
        description="Logfire project write token (required if sending to Logfire servers)",
    )
    LOGFIRE_SERVICE_NAME: str | None = Field(
        default=None,
        description="Service name for Logfire traces; defaults to APP_NAME",
    )
    LOGFIRE_ENVIRONMENT: str | None = Field(
        default=None,
        description="Deployment environment for Logfire traces (e.g. dev, staging, prod); defaults to ENV",
    )
    LOGFIRE_CONSOLE: bool = Field(
        default=True,
        description="Enable structured colored logging to terminal console",
    )

    @field_validator("USER_DATA_SOURCE", mode="before")
    @classmethod
    def parse_user_data_source(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError as e:
                raise ValueError("USER_DATA_SOURCE must be valid JSON") from e
        return value


@lru_cache()
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
