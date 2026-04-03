"""Dependency-wiring regression tests."""

from contextlib import asynccontextmanager

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from unittest.mock import MagicMock

from api.deps.db import get_db
from db.tenancy_strategy import TenantDBContext


def test_missing_tenant_fails_before_db_session_strategy_is_resolved() -> None:
    app = FastAPI()
    strategy_calls = {"count": 0}

    def forbidden_get_app_tenancy_strategy(_: FastAPI) -> object:
        strategy_calls["count"] += 1
        raise AssertionError("strategy should not be resolved")

    from api.deps import db as db_module

    original = db_module.get_app_tenancy_strategy
    db_module.get_app_tenancy_strategy = forbidden_get_app_tenancy_strategy

    @app.get("/probe")
    async def probe(_: object = Depends(get_db)) -> dict[str, bool]:
        return {"ok": True}

    try:
        with TestClient(app) as client:
            response = client.get("/probe")
    finally:
        db_module.get_app_tenancy_strategy = original

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Tenant ID is required (X-Tenant-ID header missing)"
    )
    assert strategy_calls["count"] == 0


@pytest.mark.asyncio
async def test_get_db_closes_strategy_session_on_exit() -> None:
    request = MagicMock(spec=Request)
    request.app = FastAPI()
    tenant_context = MagicMock(spec=TenantDBContext)
    close_state = {"closed": False}
    session = object()

    class FakeStrategy:
        @asynccontextmanager
        async def get_session(self, _: object):
            try:
                yield session
            finally:
                close_state["closed"] = True

    from api.deps import db as db_module

    original = db_module.get_app_tenancy_strategy
    db_module.get_app_tenancy_strategy = lambda app: FakeStrategy()
    try:
        generator = get_db(request, tenant_context)
        yielded = await anext(generator)
        assert yielded is session
        await generator.aclose()
    finally:
        db_module.get_app_tenancy_strategy = original

    assert close_state["closed"] is True
