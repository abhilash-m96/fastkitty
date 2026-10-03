"""Unit tests for user-data extraction and error mapping helpers."""

import json

import jwt
import pytest
from fastapi import HTTPException

from api.deps.user_data import (
    _build_get_user_data,
    _extract_bearer_token,
    _extract_headers,
    _extract_jwt_token,
    _extract_single_header_claims,
    _parse_roles,
)
from config.settings import (
    UserDataHeaderSource,
    UserDataJWTSource,
    UserDataSingleHeaderClaimsSource,
)


def test_parse_roles_handles_none_list_and_string() -> None:
    """Normalize missing, list-based, and comma-delimited role values."""
    assert _parse_roles(None, ",") is None
    assert _parse_roles([" admin ", "editor", ""], ",") == ["admin", "editor"]
    assert _parse_roles("admin, editor ,,author", ",") == [
        "admin",
        "editor",
        "author",
    ]


def test_parse_roles_rejects_invalid_type() -> None:
    """Reject role payloads that are neither a list nor a string."""
    with pytest.raises(ValueError, match="Roles must be a list"):
        _parse_roles({"admin": True}, ",")


def test_extract_bearer_token_accepts_prefixed_and_raw_token() -> None:
    """Support both standard bearer headers and raw-token configurations."""
    assert _extract_bearer_token("Bearer abc123", "Bearer") == "abc123"
    assert _extract_bearer_token("opaque-token", None) == "opaque-token"
    assert _extract_bearer_token(None, "Bearer") is None


def test_extract_bearer_token_rejects_invalid_format() -> None:
    """Fail when an auth header cannot be split into prefix and token."""
    with pytest.raises(ValueError, match="Invalid Authorization header format"):
        _extract_bearer_token("Bearer", "Bearer")


def test_extract_headers_builds_user_data() -> None:
    """Read user identity fields from kwargs and build UserData."""
    source = UserDataHeaderSource()
    kwargs = {
        "user_id_header": "user-1",
        "user_email_header": "user@example.com",
        "user_roles_header": "admin,editor",
    }

    user = _extract_headers(UserDataHeaderSource, source, kwargs)

    assert user.user_id == "user-1"
    assert user.email == "user@example.com"
    assert user.roles == ["admin", "editor"]


def test_extract_headers_requires_user_id() -> None:
    """Require a user ID when header-based identity is configured."""
    source = UserDataHeaderSource()
    with pytest.raises(ValueError, match="Missing required header: X-User-ID"):
        _extract_headers(UserDataHeaderSource, source, {})


def test_extract_jwt_token_decodes_claims_without_verification() -> None:
    """Decode already-validated JWT claims into UserData."""
    token = jwt.encode(
        {"sub": "user-1", "email": "user@example.com", "roles": ["author"]},
        key="test-secret-key-with-sufficient-length",
        algorithm="HS256",
    )
    source = UserDataJWTSource()

    user = _extract_jwt_token(source, token)

    assert user.user_id == "user-1"
    assert user.email == "user@example.com"
    assert user.roles == ["author"]


def test_extract_jwt_token_requires_user_id_claim() -> None:
    """Reject JWT payloads that do not contain the configured user ID claim."""
    token = jwt.encode(
        {"email": "user@example.com"},
        key="test-secret-key-with-sufficient-length",
        algorithm="HS256",
    )
    source = UserDataJWTSource()

    with pytest.raises(ValueError, match="JWT is missing required claim: sub"):
        _extract_jwt_token(source, token)


def test_extract_jwt_token_rejects_invalid_token() -> None:
    """Reject malformed JWT strings."""
    source = UserDataJWTSource()
    with pytest.raises(ValueError, match="Invalid JWT token"):
        _extract_jwt_token(source, "invalid-token-format")


def test_extract_single_header_claims_decodes_json_header() -> None:
    """Extract user data from a JSON claims header payload."""
    source = UserDataSingleHeaderClaimsSource()
    header_val = json.dumps(
        {"id": "user-1", "email": "user@example.com", "roles": ["reader"]}
    )

    user = _extract_single_header_claims(source, header_val)

    assert user.user_id == "user-1"
    assert user.email == "user@example.com"
    assert user.roles == ["reader"]


def test_extract_single_header_claims_rejects_invalid_json() -> None:
    """Reject claims headers that cannot be decoded as valid JSON."""
    source = UserDataSingleHeaderClaimsSource()
    with pytest.raises(ValueError, match="User claims header must be valid JSON"):
        _extract_single_header_claims(source, "{not-json}")


def test_extract_single_header_claims_rejects_non_object_json() -> None:
    """Reject claims headers whose JSON value is not an object."""
    source = UserDataSingleHeaderClaimsSource()
    with pytest.raises(ValueError, match="User claims header must be a JSON object"):
        _extract_single_header_claims(source, json.dumps(["user-1"]))


def test_extract_single_header_claims_requires_user_id() -> None:
    """Reject claims headers missing the user ID field."""
    source = UserDataSingleHeaderClaimsSource()
    with pytest.raises(
        ValueError, match="User claims header is missing required field: id"
    ):
        _extract_single_header_claims(source, json.dumps({"email": "user@example.com"}))


@pytest.mark.asyncio
async def test_header_handler_maps_errors_to_bad_request() -> None:
    """Translate header source validation failures into HTTP 400 responses."""
    handler = _build_get_user_data(source=UserDataHeaderSource())

    with pytest.raises(HTTPException) as exc_info:
        await handler(user_id_header=None)

    assert exc_info.value.status_code == 400
    assert "Missing required header" in exc_info.value.detail


@pytest.mark.asyncio
async def test_jwt_handler_maps_errors_to_unauthorized() -> None:
    """Translate JWT source parsing failures into HTTP 401 responses."""
    handler = _build_get_user_data(source=UserDataJWTSource())

    with pytest.raises(HTTPException) as exc_info:
        await handler(header_name="invalid")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid Authorization header format"


@pytest.mark.asyncio
async def test_claims_handler_maps_errors_to_bad_request() -> None:
    """Translate claims header parsing failures into HTTP 400 responses."""
    handler = _build_get_user_data(source=UserDataSingleHeaderClaimsSource())

    with pytest.raises(HTTPException) as exc_info:
        await handler(header_name=None)

    assert exc_info.value.status_code == 400
    assert "Missing required header" in exc_info.value.detail


@pytest.mark.asyncio
async def test_unconfigured_source_returns_none() -> None:
    """Return None when USER_DATA_SOURCE is unconfigured."""
    handler = _build_get_user_data(source=None)
    result = await handler()
    assert result is None


def test_unsupported_source_type_raises_runtime_error() -> None:
    """Raise RuntimeError at builder creation when source type is unsupported."""
    with pytest.raises(RuntimeError, match="Unsupported USER_DATA_SOURCE type"):
        _build_get_user_data(source=object())  # type: ignore[arg-type]
