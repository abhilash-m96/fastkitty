import importlib
import json
import os
import sys
from collections.abc import Callable, Generator
from pathlib import Path

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schemas.tenancy import DatabaseConfig, TenantConfig, TenantSecrets


@pytest.fixture
def app() -> Generator[FastAPI, None, None]:
    os.environ.setdefault("USER_DATA_SOURCE", json.dumps({"type": "header"}))

    from config.settings import get_settings
    import main as main_module

    get_settings.cache_clear()
    main_module = importlib.reload(main_module)

    try:
        yield main_module.app
    finally:
        main_module.app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def apply_overrides(
    app: FastAPI,
) -> Generator[
    Callable[[dict[Callable[..., object], Callable[..., object]]], None], None, None
]:
    def _apply(overrides: dict[Callable[..., object], Callable[..., object]]) -> None:
        app.dependency_overrides.update(overrides)

    try:
        yield _apply
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def tenant_config() -> TenantConfig:
    return TenantConfig(
        tenant_id="tenant_1",
        display_name="Tenant One",
        is_active=True,
        features={"greet": {"message": "Hello {tenant_name}!"}},
    )


@pytest.fixture
def inactive_tenant_config() -> TenantConfig:
    return TenantConfig(
        tenant_id="tenant_2",
        display_name="Tenant Two",
        is_active=False,
        features=None,
    )


@pytest.fixture
def tenant_secrets() -> TenantSecrets:
    return TenantSecrets(
        tenant_id="tenant_1",
        database_config=DatabaseConfig(
            host="localhost",
            port=5432,
            username="tenant_user",
            password="tenant_password",
            database_name="tenant_db",
        ),
    )


@pytest.fixture
def user_payload() -> dict[str, object]:
    return {
        "user_id": "user-123",
        "email": "user@example.com",
        "roles": ["author", "editor"],
    }


@pytest.fixture
def header_user_headers(user_payload: dict[str, object]) -> dict[str, str]:
    roles = user_payload.get("roles", [])
    role_list = roles if isinstance(roles, list) else []
    return {
        "X-Tenant-ID": "tenant_1",
        "X-User-ID": str(user_payload["user_id"]),
        "X-User-Email": str(user_payload["email"]),
        "X-User-Roles": ",".join(str(role) for role in role_list),
    }


@pytest.fixture
def claims_user_headers(user_payload: dict[str, object]) -> dict[str, str]:
    return {
        "X-Tenant-ID": "tenant_1",
        "X-User-Claims": json.dumps(
            {
                "id": user_payload["user_id"],
                "email": user_payload["email"],
                "roles": user_payload["roles"],
            }
        ),
    }


@pytest.fixture
def jwt_user_headers(user_payload: dict[str, object]) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": user_payload["user_id"],
            "email": user_payload["email"],
            "roles": user_payload["roles"],
        },
        key="test-secret-key-with-sufficient-length",
        algorithm="HS256",
    )
    return {
        "X-Tenant-ID": "tenant_1",
        "Authorization": f"Bearer {token}",
    }
