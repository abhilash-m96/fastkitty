"""Strategy-config validation tests."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config.settings import (
    Settings,
    TenancyConfigFileConnection,
    TenancySecretsFileConnection,
)
from config.tenancy_strategy_validation import (
    validate_database_config_for_strategy,
    validate_tenancy_strategy_startup,
)
from schemas.tenancy import DatabaseConfig


def _write_tenant_files(
    tmp_path: Path,
    *,
    include_schema_name: bool,
) -> tuple[str, str]:
    config_path = tmp_path / "tenants.json"
    secrets_path = tmp_path / "tenant_secrets.json"
    config_path.write_text(
        json.dumps(
            {
                "tenant_1": {
                    "tenant_id": "tenant_1",
                    "display_name": "Tenant One",
                    "is_active": True,
                    "features": {},
                }
            }
        )
    )
    database_config: dict[str, object] = {
        "host": "localhost",
        "port": 5432,
        "username": "tenant_user",
        "password": "tenant_password",
        "database_name": "tenant_db",
    }
    if include_schema_name:
        database_config["schema_name"] = "tenant_one"

    secrets_path.write_text(
        json.dumps(
            {
                "tenant_1": {
                    "tenant_id": "tenant_1",
                    "database_config": database_config,
                }
            }
        )
    )
    return str(config_path), str(secrets_path)


def test_schema_strategy_requires_schema_name() -> None:
    """Reject schema mode when the current tenant DB payload omits a schema name."""
    db_config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="tenant_user",
        password="tenant_password",
        database_name="tenant_db",
    )

    with pytest.raises(
        ValueError,
        match="must define database_config.schema_name when TENANCY_DB_STRATEGY='schema'",
    ):
        validate_database_config_for_strategy(
            db_config,
            "schema",
            tenant_id="tenant_1",
        )


def test_schema_strategy_startup_validation_accepts_schema_names(
    tmp_path: Path,
) -> None:
    """Allow startup when file-backed tenant secrets provide schema names."""
    config_path, secrets_path = _write_tenant_files(
        tmp_path,
        include_schema_name=True,
    )
    settings = Settings.model_construct(
        TENANCY_DB_STRATEGY="schema",
        TENANCY_CONFIG_CONNECTION=TenancyConfigFileConnection(file_path=config_path),
        TENANCY_SECRETS_CONNECTION=TenancySecretsFileConnection(file_path=secrets_path),
        USER_DATA_SOURCE={"type": "header"},
    )

    validate_tenancy_strategy_startup(settings)


def test_schema_strategy_startup_validation_rejects_missing_schema_name(
    tmp_path: Path,
) -> None:
    """Fail fast on startup for file-backed schema mode without schema names."""
    config_path, secrets_path = _write_tenant_files(
        tmp_path,
        include_schema_name=False,
    )
    settings = Settings.model_construct(
        TENANCY_DB_STRATEGY="schema",
        TENANCY_CONFIG_CONNECTION=TenancyConfigFileConnection(file_path=config_path),
        TENANCY_SECRETS_CONNECTION=TenancySecretsFileConnection(file_path=secrets_path),
        USER_DATA_SOURCE={"type": "header"},
    )

    with pytest.raises(
        ValueError,
        match="Tenant 'tenant_1' must define database_config.schema_name",
    ):
        validate_tenancy_strategy_startup(settings)


def test_app_startup_fails_fast_for_invalid_schema_strategy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Surface strategy-config errors during FastAPI startup."""
    import importlib

    config_path, secrets_path = _write_tenant_files(
        tmp_path,
        include_schema_name=False,
    )
    monkeypatch.setenv("USER_DATA_SOURCE", json.dumps({"type": "header"}))
    monkeypatch.setenv("TENANCY_DB_STRATEGY", "schema")
    monkeypatch.setenv(
        "TENANCY_CONFIG_CONNECTION",
        json.dumps({"type": "file", "file_path": config_path}),
    )
    monkeypatch.setenv(
        "TENANCY_SECRETS_CONNECTION",
        json.dumps({"type": "file", "file_path": secrets_path}),
    )

    from config.settings import get_settings
    import main as main_module

    get_settings.cache_clear()
    main_module = importlib.reload(main_module)

    with pytest.raises(
        ValueError,
        match="Tenant 'tenant_1' must define database_config.schema_name",
    ):
        with TestClient(main_module.app):
            pass

    get_settings.cache_clear()
