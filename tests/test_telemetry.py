from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from opentelemetry import trace

from config.settings import Settings
from config.telemetry import (
    enrich_span_with_tenant,
    enrich_span_with_user,
    setup_telemetry,
)


def test_setup_telemetry_disabled():
    app = FastAPI()
    settings = Settings(LOGFIRE_ENABLED=False)

    with patch("logfire.configure") as mock_configure:
        setup_telemetry(app, settings)
        mock_configure.assert_not_called()


def test_setup_telemetry_default_console_mode():
    app = FastAPI()
    settings = Settings(
        LOGFIRE_ENABLED=True,
        LOGFIRE_SEND_TO_LOGFIRE=False,
        ENV="staging",
        APP_NAME="custom-fastkitty",
    )

    with (
        patch("logfire.configure") as mock_configure,
        patch("logfire.instrument_fastapi") as mock_fastapi,
        patch("logfire.instrument_pydantic") as mock_pydantic,
        patch("logfire.instrument_sqlalchemy") as mock_sa,
    ):
        setup_telemetry(app, settings)

        mock_configure.assert_called_once_with(
            token=None,
            send_to_logfire=False,
            environment="staging",
            service_name="custom-fastkitty",
            service_version=settings.VERSION,
            console=True,
        )
        mock_fastapi.assert_called_once_with(app, capture_headers=False)
        mock_pydantic.assert_not_called()
        mock_sa.assert_called_once()


def test_setup_telemetry_custom_environment():
    app = FastAPI()
    settings = Settings(
        LOGFIRE_ENABLED=True,
        LOGFIRE_SEND_TO_LOGFIRE=True,
        LOGFIRE_TOKEN="test-token-123",
        LOGFIRE_ENVIRONMENT="prod",
        LOGFIRE_SERVICE_NAME="prod-service",
    )

    with (
        patch("logfire.configure") as mock_configure,
        patch("logfire.instrument_fastapi"),
        patch("logfire.instrument_pydantic") as mock_pydantic,
        patch("logfire.instrument_sqlalchemy"),
    ):
        setup_telemetry(app, settings)

        mock_configure.assert_called_once_with(
            token="test-token-123",
            send_to_logfire=True,
            environment="prod",
            service_name="prod-service",
            service_version=settings.VERSION,
            console=True,
        )
        mock_pydantic.assert_not_called()


def test_enrich_span_with_tenant_when_recording():
    mock_span = MagicMock()
    mock_span.is_recording.return_value = True

    with patch.object(trace, "get_current_span", return_value=mock_span):
        enrich_span_with_tenant("Tenant_1", display_name="Tenant One")

        mock_span.set_attribute.assert_any_call("tenant.id", "tenant_1")
        mock_span.set_attribute.assert_any_call("tenant_id", "tenant_1")
        mock_span.set_attribute.assert_any_call("tenant.name", "Tenant One")


def test_enrich_span_with_tenant_when_not_recording():
    mock_span = MagicMock()
    mock_span.is_recording.return_value = False

    with patch.object(trace, "get_current_span", return_value=mock_span):
        enrich_span_with_tenant("tenant_1")
        mock_span.set_attribute.assert_not_called()


def test_enrich_span_with_user_when_recording():
    mock_span = MagicMock()
    mock_span.is_recording.return_value = True

    with patch.object(trace, "get_current_span", return_value=mock_span):
        enrich_span_with_user(
            user_id="user_42",
            email="user42@example.com",
            roles=["admin", "member"],
        )

        mock_span.set_attribute.assert_any_call("user.id", "user_42")
        mock_span.set_attribute.assert_any_call("user_id", "user_42")
        # Ensure email PII is omitted from spans
        for call_args in mock_span.set_attribute.call_args_list:
            assert "user.email" not in call_args[0]
        mock_span.set_attribute.assert_any_call("user.roles", ["admin", "member"])


def test_enrich_span_with_user_when_not_recording():
    mock_span = MagicMock()
    mock_span.is_recording.return_value = False

    with patch.object(trace, "get_current_span", return_value=mock_span):
        enrich_span_with_user(user_id="user_1")
        mock_span.set_attribute.assert_not_called()
