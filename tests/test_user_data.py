"""Unit tests for user-data extraction and error mapping helpers."""

import json

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.deps.user_data import (
    _extract_bearer_token,
    _from_claims,
    _from_headers,
    _from_jwt,
    _parse_roles,
    get_user_data,
)
from config.settings import (
    Settings,
    UserDataHeaderSource,
    UserDataJWTSource,
    UserDataSingleHeaderClaimsSource,
)


def _request(headers: dict[str, str]) -> Request:
    """Build a minimal Starlette request object for dependency testing."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in headers.items()
            ],
        }
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


def test_extract_bearer_token_rejects_invalid_format() -> None:
    """Fail when an auth header cannot be split into prefix and token."""
    with pytest.raises(ValueError, match="Invalid Authorization header format"):
        _extract_bearer_token("Bearer", "Bearer")


def test_from_headers_extracts_user_payload() -> None:
    """Read user identity fields from the configured request headers."""
    source = UserDataHeaderSource()
    request = _request(
        {
            "X-User-ID": "user-1",
            "X-User-Email": "user@example.com",
            "X-User-Roles": "admin,editor",
        }
    )

    payload = _from_headers(source, request)

    assert payload == {
        "user_id": "user-1",
        "email": "user@example.com",
        "roles": ["admin", "editor"],
    }


def test_from_headers_requires_user_id() -> None:
    """Require a user ID when header-based identity is configured."""
    with pytest.raises(ValueError, match="User ID header is required"):
        _from_headers(UserDataHeaderSource(), _request({}))


def test_from_jwt_decodes_claims_without_verification() -> None:
    """Decode already-validated JWT claims into the normalized payload shape."""
    token = jwt.encode(
        {"sub": "user-1", "email": "user@example.com", "roles": ["author"]},
        key="test-secret-key-with-sufficient-length",
        algorithm="HS256",
    )
    source = UserDataJWTSource()

    payload = _from_jwt(source, _request({"Authorization": f"Bearer {token}"}))

    assert payload == {
        "user_id": "user-1",
        "email": "user@example.com",
        "roles": ["author"],
    }


def test_from_jwt_requires_user_id_claim() -> None:
    """Reject JWT payloads that do not contain the configured user ID claim."""
    token = jwt.encode(
        {"email": "user@example.com"},
        key="test-secret-key-with-sufficient-length",
        algorithm="HS256",
    )

    with pytest.raises(ValueError, match="JWT is missing user id claim"):
        _from_jwt(UserDataJWTSource(), _request({"Authorization": f"Bearer {token}"}))


def test_from_claims_decodes_json_header() -> None:
    """Extract user data from a JSON claims header payload."""
    source = UserDataSingleHeaderClaimsSource()
    request = _request(
        {
            "X-User-Claims": json.dumps(
                {"id": "user-1", "email": "user@example.com", "roles": ["reader"]}
            )
        }
    )

    payload = _from_claims(source, request)

    assert payload == {
        "user_id": "user-1",
        "email": "user@example.com",
        "roles": ["reader"],
    }


def test_from_claims_rejects_non_object_json() -> None:
    """Reject claims headers whose JSON value is not an object."""
    with pytest.raises(ValueError, match="User claims header must be a JSON object"):
        _from_claims(
            UserDataSingleHeaderClaimsSource(),
            _request({"X-User-Claims": json.dumps(["user-1"])}),
        )


def test_get_user_data_maps_header_errors_to_bad_request() -> None:
    """Translate header source validation failures into HTTP 400 responses."""
    settings = Settings.model_construct(USER_DATA_SOURCE=UserDataHeaderSource())

    with pytest.raises(HTTPException) as exc_info:
        get_user_data(_request({}), settings)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "User ID header is required"


def test_get_user_data_maps_jwt_errors_to_unauthorized() -> None:
    """Translate JWT source parsing failures into HTTP 401 responses."""
    settings = Settings.model_construct(USER_DATA_SOURCE=UserDataJWTSource())

    with pytest.raises(HTTPException) as exc_info:
        get_user_data(_request({"Authorization": "invalid"}), settings)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid Authorization header format"


def test_get_user_data_rejects_unsupported_source_type() -> None:
    """Return a 500 error if settings point to an unsupported source object."""
    settings = Settings.model_construct(USER_DATA_SOURCE=object())

    with pytest.raises(HTTPException) as exc_info:
        get_user_data(_request({}), settings)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Unsupported user data source"
