import inspect
import json
import logging
import types
import typing
from collections.abc import Callable
from typing import Any, Coroutine, Literal, get_origin, get_args, Union

import jwt
from fastapi import HTTPException, Header, Request, status
from jwt import PyJWTError


from config.settings import (
    UserDataHeaderSource,
    UserDataJWTSource,
    UserDataSingleHeaderClaimsSource,
    UserDataSource,
    get_settings,
)
from config.telemetry import enrich_span_with_user
from schemas.user_data import UserData

logger = logging.getLogger(__name__)

_source = get_settings().USER_DATA_SOURCE


# -----------------------
# Helpers
# -----------------------


def _is_literal_field(field_info) -> bool:
    return typing.get_origin(field_info.annotation) is Literal


def _is_optional(annotation) -> bool:
    return get_origin(annotation) in (Union, types.UnionType) and type(
        None
    ) in get_args(annotation)


def _is_field_active(src, field_name: str, field_info) -> bool:
    if _is_literal_field(field_info):
        return False
    if src.model_fields_set:
        if field_name in src.model_fields_set:
            return getattr(src, field_name) is not None
        if not _is_optional(field_info.annotation):
            return getattr(src, field_name) is not None
        return False
    return getattr(src, field_name) is not None


def _parse_roles(value: object | None, delimiter: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(delimiter) if item.strip()]
    raise ValueError("Roles must be a list or delimiter-separated string")


def _extract_bearer_token(header_value: str | None, prefix: str | None) -> str | None:
    if not header_value:
        return None
    if not prefix:
        return header_value
    parts = header_value.split()
    if len(parts) == 2 and parts[0].lower() == prefix.lower():
        return parts[1]
    raise ValueError("Invalid Authorization header format")


def _extract_jwt_token(
    source: UserDataJWTSource,
    token: str,
    expected_tenant_id: str | None = None,
) -> UserData:
    """Extract and parse claims from a JWT token without cryptographic verification.

    IMPORTANT ARCHITECTURAL SECURITY NOTE:
    FastKitty services operate behind an API Gateway (or BFF) on a trusted internal
    network where authentication (signature verification, expiration, issuer checks)
    is handled upstream. The service extracts identity claims for tenant isolation and
    logging without the CPU overhead of redundant re-verification. If the service is
    ever exposed directly to public internet traffic without an upstream gateway,
    cryptographic signature verification MUST be enforced.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except PyJWTError as exc:
        raise ValueError("Invalid JWT token") from exc

    alg_header = unverified_header.get("alg")
    if not isinstance(alg_header, str) or alg_header.lower() == "none":
        raise ValueError("JWT 'none' algorithm is forbidden")

    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except PyJWTError as exc:
        raise ValueError("Invalid JWT token") from exc

    if expected_tenant_id:
        if source.tenant_id_claim:
            token_tenant = claims.get(source.tenant_id_claim)
            claim_desc = f"'{source.tenant_id_claim}'"
        else:
            token_tenant = (
                claims.get("tenant_id") or claims.get("tid") or claims.get("tenant")
            )
            claim_desc = "tenant claim"

        must_have_claim = (
            source.require_tenant_claim or get_settings().REQUIRE_TENANT_CLAIM
        )
        if token_tenant is None and must_have_claim:
            raise PermissionError(
                f"Token is missing required {claim_desc} matching requested tenant '{expected_tenant_id}'"
            )
        if (
            token_tenant is not None
            and str(token_tenant).strip().lower() != expected_tenant_id.strip().lower()
        ):
            raise PermissionError(
                f"Token tenant '{token_tenant}' does not match requested tenant '{expected_tenant_id}'"
            )

    result = {}
    for field_name, field_info in UserDataJWTSource.model_fields.items():
        if not _is_field_active(source, field_name, field_info):
            continue
        claim_key = getattr(source, field_name)
        if not isinstance(claim_key, str):
            continue
        if field_name not in UserDataJWTSource._payload_key_map:
            continue
        payload_key = UserDataJWTSource._payload_key_map[field_name]
        value = claims.get(claim_key)
        if value is None and not _is_optional(field_info.annotation):
            raise ValueError(f"JWT is missing required claim: {claim_key}")
        result[payload_key] = value

    result["roles"] = _parse_roles(result.get("roles"), ",")
    return UserData(**result)


def _extract_single_header_claims(
    source: UserDataSingleHeaderClaimsSource,
    header_value: str,
    expected_tenant_id: str | None = None,
) -> UserData:
    try:
        claims = json.loads(header_value)
    except json.JSONDecodeError as exc:
        raise ValueError("User claims header must be valid JSON") from exc

    if not isinstance(claims, dict):
        raise ValueError("User claims header must be a JSON object")

    if expected_tenant_id:
        if source.tenant_id_field:
            claims_tenant = claims.get(source.tenant_id_field)
            claim_desc = f"'{source.tenant_id_field}'"
        else:
            claims_tenant = (
                claims.get("tenant_id") or claims.get("tid") or claims.get("tenant")
            )
            claim_desc = "tenant claim"

        must_have_claim = (
            source.require_tenant_claim or get_settings().REQUIRE_TENANT_CLAIM
        )
        if claims_tenant is None and must_have_claim:
            raise PermissionError(
                f"Claims header is missing required {claim_desc} matching requested tenant '{expected_tenant_id}'"
            )
        if (
            claims_tenant is not None
            and str(claims_tenant).strip().lower() != expected_tenant_id.strip().lower()
        ):
            raise PermissionError(
                f"Claims tenant '{claims_tenant}' does not match requested tenant '{expected_tenant_id}'"
            )

    result = {}
    for field_name, field_info in UserDataSingleHeaderClaimsSource.model_fields.items():
        if not _is_field_active(source, field_name, field_info):
            continue
        claim_key = getattr(source, field_name)
        if not isinstance(claim_key, str):
            continue
        if field_name not in UserDataSingleHeaderClaimsSource._payload_key_map:
            continue
        payload_key = UserDataSingleHeaderClaimsSource._payload_key_map[field_name]
        value = claims.get(claim_key)
        if value is None and not _is_optional(field_info.annotation):
            raise ValueError(
                f"User claims header is missing required field: {claim_key}"
            )
        result[payload_key] = value

    if "roles" in result and result["roles"] is not None:
        result["roles"] = _parse_roles(result["roles"], ",")

    return UserData(**result)


async def _get_user_data_unconfigured() -> UserData | None:
    logger.warning("get_user_data() called but USER_DATA_SOURCE is not configured.")
    return None


# -----------------------
# Signature builder
# -----------------------


def _build_dynamic_signature(model_class, src) -> inspect.Signature:
    params = []

    if isinstance(src, UserDataHeaderSource):
        target_fields = [
            f
            for f in model_class._payload_key_map.keys()
            if f in model_class.model_fields
        ]
    else:
        target_fields = ["header_name"]

    for field_name in target_fields:
        field_info = model_class.model_fields[field_name]
        if not _is_field_active(src, field_name, field_info):
            continue
        header_name = getattr(src, field_name)
        if not isinstance(header_name, str):
            continue
        is_required = not _is_optional(field_info.annotation)
        param = inspect.Parameter(
            field_name,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=Header(..., alias=header_name)
            if is_required
            else Header(None, alias=header_name),
            annotation=str if is_required else str | None,
        )
        params.append(param)

    # Allow Request injection for cross-tenant validation without exposing it in OpenAPI parameters
    params.append(
        inspect.Parameter(
            "request",
            inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=Request,
        )
    )

    return inspect.Signature(params)


def _extract_headers(model_class, src, kwargs: dict) -> UserData:
    result = {}
    payload_key_map = getattr(model_class, "_payload_key_map", {})
    for field_name, field_info in model_class.model_fields.items():
        if not _is_field_active(src, field_name, field_info):
            continue
        if field_name not in payload_key_map:
            continue
        payload_key = payload_key_map[field_name]
        value = kwargs.get(field_name)
        if value is None and not _is_optional(field_info.annotation):
            raise ValueError(f"Missing required header: {getattr(src, field_name)}")
        result[payload_key] = value

    if "roles" in result and result["roles"] is not None:
        delimiter = getattr(src, "roles_delimiter", ",")
        result["roles"] = _parse_roles(result["roles"], delimiter)

    return UserData(**result)


# -----------------------
# Main builder
# -----------------------

_UNSET = object()


def _build_get_user_data(
    source: UserDataSource | object = _UNSET,
) -> Callable[..., Any]:
    src = get_settings().USER_DATA_SOURCE if source is _UNSET else source
    if src is None:
        return _get_user_data_unconfigured

    # -----------------------
    # HEADER MODE
    # -----------------------
    if isinstance(src, UserDataHeaderSource):

        async def _header_handler(**kwargs) -> UserData:
            try:
                user_data = _extract_headers(UserDataHeaderSource, src, kwargs)
                enrich_span_with_user(
                    user_id=user_data.user_id,
                    email=user_data.email,
                    roles=user_data.roles,
                )
                return user_data
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc

        setattr(
            _header_handler,
            "__signature__",
            _build_dynamic_signature(UserDataHeaderSource, src),
        )
        _header_handler.__name__ = "get_user_data"
        return _header_handler

    # -----------------------
    # JWT MODE
    # -----------------------
    if isinstance(src, UserDataJWTSource):

        async def _jwt_handler(**kwargs) -> UserData:
            try:
                auth_header = kwargs.get("header_name")
                token = _extract_bearer_token(auth_header, src.prefix)
                if not token:
                    raise ValueError("Authorization token is required")

                request: Request | None = kwargs.get("request")
                expected_tenant_id = kwargs.get("expected_tenant_id")
                if not expected_tenant_id and request is not None:
                    expected_tenant_id = request.headers.get("x-tenant-id")

                user_data = _extract_jwt_token(
                    src, token, expected_tenant_id=expected_tenant_id
                )
                enrich_span_with_user(
                    user_id=user_data.user_id,
                    email=user_data.email,
                    roles=user_data.roles,
                )
                return user_data
            except PermissionError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=str(exc),
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=str(exc),
                ) from exc

        setattr(
            _jwt_handler,
            "__signature__",
            _build_dynamic_signature(UserDataJWTSource, src),
        )
        _jwt_handler.__name__ = "get_user_data"
        return _jwt_handler

    # -----------------------
    # CLAIMS MODE
    # -----------------------
    if isinstance(src, UserDataSingleHeaderClaimsSource):

        async def _claims_handler(**kwargs) -> UserData:
            try:
                claims_header = kwargs.get("header_name")
                if not claims_header:
                    raise ValueError(f"Missing required header: {src.header_name}")

                request: Request | None = kwargs.get("request")
                expected_tenant_id = kwargs.get("expected_tenant_id")
                if not expected_tenant_id and request is not None:
                    expected_tenant_id = request.headers.get("x-tenant-id")

                user_data = _extract_single_header_claims(
                    src, claims_header, expected_tenant_id=expected_tenant_id
                )
                enrich_span_with_user(
                    user_id=user_data.user_id,
                    email=user_data.email,
                    roles=user_data.roles,
                )
                return user_data
            except PermissionError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=str(exc),
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc

        setattr(
            _claims_handler,
            "__signature__",
            _build_dynamic_signature(UserDataSingleHeaderClaimsSource, src),
        )
        _claims_handler.__name__ = "get_user_data"
        return _claims_handler

    raise RuntimeError(f"Unsupported USER_DATA_SOURCE type: {src!r}")


# -----------------------
# Exported dependency
# -----------------------

get_user_data: Callable[..., Coroutine[Any, Any, UserData | None]] = (
    _build_get_user_data()
)
