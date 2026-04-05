import inspect
import json
import logging
import typing
from collections.abc import Callable
from typing import Any, Coroutine, Literal, get_origin, get_args, Union

import jwt
from fastapi import HTTPException, Header, status
from jwt import PyJWTError

from config.settings import (
    UserDataHeaderSource,
    UserDataJWTSource,
    UserDataSingleHeaderClaimsSource,
    get_settings,
)
from schemas.user_data import UserData

logger = logging.getLogger(__name__)

_source = get_settings().USER_DATA_SOURCE


# -----------------------
# Helpers
# -----------------------


def _is_literal_field(field_info) -> bool:
    return typing.get_origin(field_info.annotation) is Literal


def _is_optional(annotation) -> bool:
    return get_origin(annotation) is Union and type(None) in get_args(annotation)


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


def _extract_jwt_token(source: UserDataJWTSource, token: str) -> UserData:
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except PyJWTError as exc:
        raise ValueError("Invalid JWT token") from exc

    result = {}
    for field_name, field_info in UserDataJWTSource.model_fields.items():
        if _is_literal_field(field_info):
            continue
        if field_name not in source.model_fields_set:
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
    source: UserDataSingleHeaderClaimsSource, header_value: str
) -> UserData:
    try:
        claims = json.loads(header_value)
    except json.JSONDecodeError as exc:
        raise ValueError("User claims header must be valid JSON") from exc

    if not isinstance(claims, dict):
        raise ValueError("User claims header must be a JSON object")

    result = {}
    for field_name, field_info in UserDataSingleHeaderClaimsSource.model_fields.items():
        if _is_literal_field(field_info):
            continue
        if field_name not in source.model_fields_set:
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

    return UserData(**result)


async def _get_user_data_unconfigured() -> UserData | None:
    logger.warning("get_user_data() called but USER_DATA_SOURCE is not configured.")
    return None


# -----------------------
# Signature builder
# -----------------------


def _build_dynamic_signature(model_class, src) -> inspect.Signature:
    params = []

    for field_name, field_info in model_class.model_fields.items():
        if _is_literal_field(field_info):
            continue
        if field_name not in src.model_fields_set:
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

    return inspect.Signature(params)


def _extract_headers(model_class, src, kwargs: dict) -> UserData:
    result = {}
    payload_key_map = getattr(model_class, "_payload_key_map", {})
    for field_name, field_info in model_class.model_fields.items():
        if _is_literal_field(field_info):
            continue
        if field_name not in src.model_fields_set:
            continue
        if field_name not in payload_key_map:
            continue
        payload_key = payload_key_map[field_name]
        result[payload_key] = kwargs.get(field_name)
    return UserData(**result)


# -----------------------
# Main builder
# -----------------------


def _build_get_user_data() -> Callable[..., Any]:
    if _source is None:
        return _get_user_data_unconfigured

    # -----------------------
    # HEADER MODE
    # -----------------------
    if isinstance(_source, UserDataHeaderSource):
        src = _source

        async def _header_handler(**kwargs) -> UserData:
            try:
                return _extract_headers(UserDataHeaderSource, src, kwargs)
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
    if isinstance(_source, UserDataJWTSource):
        src = _source

        async def _jwt_handler(**kwargs) -> UserData:
            try:
                auth_header = kwargs.get("header_name")
                token = _extract_bearer_token(auth_header, src.prefix)
                if not token:
                    raise ValueError("Authorization token is required")
                return _extract_jwt_token(src, token)
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
    if isinstance(_source, UserDataSingleHeaderClaimsSource):
        src = _source

        async def _claims_handler(**kwargs) -> UserData:
            try:
                claims_header = kwargs.get("header_name")
                if not claims_header:
                    raise ValueError(f"Missing required header: {src.header_name}")
                return _extract_single_header_claims(src, claims_header)
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

    raise RuntimeError(f"Unsupported USER_DATA_SOURCE type: {_source!r}")


# -----------------------
# Exported dependency
# -----------------------

get_user_data: Callable[..., Coroutine[Any, Any, UserData | None]] = (
    _build_get_user_data()
)
