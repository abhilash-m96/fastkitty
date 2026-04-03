import inspect
import json
import logging
import typing
from collections.abc import Callable
from typing import Any, Literal, get_origin, get_args, Union

import jwt
from fastapi import HTTPException, Header, Request, status
from jwt import PyJWTError

from config.settings import (
    UserDataHeaderSource,
    UserDataJWTSource,
    UserDataSingleHeaderClaimsSource,
    get_settings,
)

logger = logging.getLogger(__name__)

UserDataPayload = dict[str, object | None]

_source = get_settings().USER_DATA_SOURCE


# -----------------------
# Helpers
# -----------------------


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


def _from_jwt_token(source: UserDataJWTSource, token: str) -> UserDataPayload:
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except PyJWTError as exc:
        raise ValueError("Invalid JWT token") from exc

    user_id = claims.get(source.user_id_claim)
    if not user_id:
        raise ValueError("JWT is missing user id claim")

    email = claims.get(source.user_email_claim) if source.user_email_claim else None
    roles_value = (
        claims.get(source.user_roles_claim) if source.user_roles_claim else None
    )
    roles = _parse_roles(roles_value, ",")

    return {"user_id": str(user_id), "email": email, "roles": roles}


def _from_claims_header(
    source: UserDataSingleHeaderClaimsSource, header_value: str
) -> UserDataPayload:
    try:
        claims = json.loads(header_value)
    except json.JSONDecodeError as exc:
        raise ValueError("User claims header must be valid JSON") from exc

    if not isinstance(claims, dict):
        raise ValueError("User claims header must be a JSON object")

    user_id = claims.get(source.user_id_field)
    if not user_id:
        raise ValueError("User claims header is missing user id field")

    email = claims.get(source.user_email_field) if source.user_email_field else None
    roles_value = (
        claims.get(source.user_roles_field) if source.user_roles_field else None
    )
    roles = _parse_roles(roles_value, ",")

    return {"user_id": str(user_id), "email": email, "roles": roles}


async def _get_user_data_unconfigured() -> UserDataPayload | None:
    logger.warning(
        "get_user_data() called but USER_DATA_SOURCE is not configured. "
        "If this service requires user identity, set USER_DATA_SOURCE in .env."
    )
    return None


# -----------------------
# Signature builder
# -----------------------


def _is_literal_field(field_info) -> bool:
    return typing.get_origin(field_info.annotation) is Literal


def _is_optional(annotation) -> bool:
    return get_origin(annotation) is Union and type(None) in get_args(annotation)


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


def _extract_header_values(model_class, src, kwargs: dict) -> dict[str, str | None]:
    result = {}
    for field_name, field_info in model_class.model_fields.items():
        if _is_literal_field(field_info):
            continue
        if field_name not in src.model_fields_set:
            continue
        header_name = getattr(src, field_name)
        if not isinstance(header_name, str):
            continue
        result[field_name] = kwargs.get(field_name)
    return result


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

        async def _header_handler(request: Request, **kwargs) -> UserDataPayload:
            try:
                extracted = _extract_header_values(UserDataHeaderSource, src, kwargs)
                return {field_name: value for field_name, value in extracted.items()}
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

        async def _jwt_handler(request: Request, **kwargs) -> UserDataPayload:
            try:
                extracted = _extract_header_values(UserDataJWTSource, src, kwargs)
                auth_header = extracted.get("header_name")
                token = _extract_bearer_token(auth_header, src.prefix)
                if not token:
                    raise ValueError("Authorization token is required")
                return _from_jwt_token(src, token)
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

        async def _claims_handler(request: Request, **kwargs) -> UserDataPayload:
            try:
                extracted = _extract_header_values(
                    UserDataSingleHeaderClaimsSource, src, kwargs
                )
                claims_header = extracted.get("header_name")
                if not claims_header:
                    raise ValueError(f"Missing required header: {src.header_name}")
                return _from_claims_header(src, claims_header)
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

    raise RuntimeError(
        f"Unsupported USER_DATA_SOURCE type: {_source!r}. "
        "This is a bug — please report it."
    )


# -----------------------
# Exported dependency
# -----------------------

get_user_data = _build_get_user_data()
