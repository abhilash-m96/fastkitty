from __future__ import annotations

import logging
import re
from fastapi import FastAPI, Request
import logfire
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from config.settings import Settings

logger = logging.getLogger(__name__)


def enrich_span_with_tenant(tenant_id: str, display_name: str | None = None) -> None:
    """Enrich the current active OpenTelemetry / Logfire span with tenant context."""
    span = trace.get_current_span()
    if span.is_recording():
        clean_tenant = tenant_id.strip().lower()
        span.set_attribute("tenant.id", clean_tenant)
        span.set_attribute("tenant_id", clean_tenant)
        if display_name:
            span.set_attribute("tenant.name", display_name)


def enrich_span_with_user(
    user_id: str | None = None,
    email: str | None = None,
    roles: list[str] | None = None,
) -> None:
    """Enrich the current active OpenTelemetry / Logfire span with user identity context."""
    span = trace.get_current_span()
    if span.is_recording():
        if user_id:
            span.set_attribute("user.id", user_id)
            span.set_attribute("user_id", user_id)
        # Note: email is omitted from telemetry spans to prevent PII leakage
        if roles:
            span.set_attribute("user.roles", roles)


_SAFE_HEADER_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$")


class LogfireTenantMiddleware(BaseHTTPMiddleware):
    """
    Middleware that captures tenant and user headers from incoming HTTP requests
    and attaches them as indexed attributes on the root Logfire/OTel span.
    Only attaches sanitized identifiers matching safe regex to prevent injecting arbitrary payloads.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        span = trace.get_current_span()
        if span.is_recording():
            tenant_id = request.headers.get("x-tenant-id")
            if tenant_id:
                clean_tenant = tenant_id.strip().lower()
                if _SAFE_HEADER_PATTERN.fullmatch(clean_tenant):
                    span.set_attribute("tenant.id", clean_tenant)
                    span.set_attribute("tenant_id", clean_tenant)

            user_id = request.headers.get("x-user-id")
            if user_id:
                clean_user = user_id.strip()
                if _SAFE_HEADER_PATTERN.fullmatch(clean_user):
                    span.set_attribute("user.id", clean_user)
                    span.set_attribute("user_id", clean_user)

        response = await call_next(request)
        return response


def setup_telemetry(app: FastAPI, settings: Settings) -> None:
    """
    Initialize Pydantic Logfire and instrument FastAPI and SQLAlchemy.

    By default:
    - `LOGFIRE_SEND_TO_LOGFIRE=False`: Logs and spans are rendered in the console with zero network traffic.
    - `LOGFIRE_SEND_TO_LOGFIRE=True`: Exports spans to Logfire servers using `LOGFIRE_TOKEN`.
    - `LOGFIRE_ENVIRONMENT`: Inherits from `settings.ENV` (dev, staging, prod) for dashboard filtering.
    """
    if not settings.LOGFIRE_ENABLED:
        logger.info("Logfire telemetry is disabled (LOGFIRE_ENABLED=False)")
        return

    environment = settings.LOGFIRE_ENVIRONMENT or settings.ENV
    service_name = settings.LOGFIRE_SERVICE_NAME or settings.APP_NAME

    try:
        logfire.configure(
            token=settings.LOGFIRE_TOKEN,
            send_to_logfire=settings.LOGFIRE_SEND_TO_LOGFIRE,
            environment=environment,
            service_name=service_name,
            service_version=settings.VERSION,
            console=settings.LOGFIRE_CONSOLE,
        )
    except Exception as e:
        logger.warning("Failed to initialize Logfire telemetry: %s", e)
        return

    # Instrument FastAPI requests and response lifecycles
    try:
        logfire.instrument_fastapi(
            app, capture_headers=settings.LOGFIRE_CAPTURE_HEADERS
        )
    except Exception as e:
        logger.warning("Failed to instrument FastAPI with Logfire: %s", e)

    # Note: logfire.instrument_pydantic() is intentionally NOT called to prevent
    # DatabaseConfig and TenantSecrets plaintext passwords from being recorded in spans.

    # Instrument SQLAlchemy queries globally (across all tenant engines)
    try:
        logfire.instrument_sqlalchemy()
    except Exception as e:
        logger.warning("Failed to instrument SQLAlchemy with Logfire: %s", e)

    # Bridge Python standard logging to Logfire spans
    logging.getLogger().addHandler(logfire.LogfireLoggingHandler())

    # Add Tenant / User context enrichment middleware
    app.add_middleware(LogfireTenantMiddleware)
    logger.info(
        "Logfire telemetry initialized (service=%s, env=%s, send_to_cloud=%s)",
        service_name,
        environment,
        settings.LOGFIRE_SEND_TO_LOGFIRE,
    )
