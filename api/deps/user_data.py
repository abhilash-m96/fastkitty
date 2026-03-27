import json

from fastapi import Depends, HTTPException, Request, status
import jwt
from jwt import PyJWTError

from config.settings import (
    Settings,
    UserDataHeaderSource,
    UserDataJWTSource,
    UserDataSingleHeaderClaimsSource,
    get_settings,
)


UserDataPayload = dict[str, object | None]


def _parse_roles(value: object | None, delimiter: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(delimiter) if item.strip()]
    raise ValueError("Roles must be a list or delimiter-separated string")


def _from_headers(source: UserDataHeaderSource, request: Request) -> UserDataPayload:
    user_id = request.headers.get(source.user_id_header)
    if not user_id:
        raise ValueError("User ID header is required")

    email = (
        request.headers.get(source.user_email_header)
        if source.user_email_header
        else None
    )
    roles_value = (
        request.headers.get(source.user_roles_header)
        if source.user_roles_header
        else None
    )
    roles = _parse_roles(roles_value, source.roles_delimiter)

    return {"user_id": user_id, "email": email, "roles": roles}


def _extract_bearer_token(header_value: str | None, prefix: str | None) -> str | None:
    if not header_value:
        return None
    if not prefix:
        return header_value
    parts = header_value.split()
    if len(parts) == 2 and parts[0].lower() == prefix.lower():
        return parts[1]
    raise ValueError("Invalid Authorization header format")


def _from_jwt(source: UserDataJWTSource, request: Request) -> UserDataPayload:
    auth_header = request.headers.get(source.header_name)
    token = _extract_bearer_token(auth_header, source.prefix)
    if not token:
        raise ValueError("Authorization token is required")

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


def _from_claims(
    source: UserDataSingleHeaderClaimsSource, request: Request
) -> UserDataPayload:
    header_value = request.headers.get(source.header_name)
    if not header_value:
        raise ValueError("User claims header is required")

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


def get_user_data(
    request: Request, settings: Settings = Depends(get_settings)
) -> UserDataPayload:
    source = settings.USER_DATA_SOURCE

    try:
        if isinstance(source, UserDataHeaderSource):
            return _from_headers(source, request)
        if isinstance(source, UserDataJWTSource):
            return _from_jwt(source, request)
        if isinstance(source, UserDataSingleHeaderClaimsSource):
            return _from_claims(source, request)
    except ValueError as exc:
        if isinstance(source, UserDataJWTSource):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unsupported user data source",
    )
