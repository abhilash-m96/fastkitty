from enum import Enum
from pydantic import BaseModel, field_validator


class UserDataField(str, Enum):
    """
    Canonical field names for the resolved user data payload.

    Used as references in each source model's ``_payload_key_map`` to ensure
    that regardless of the source type (header, JWT, claims), the resolved
    payload always uses consistent, well-known keys.

    Adding a new field here should be accompanied by a corresponding field
    in :class:`UserData` and an entry in the ``_payload_key_map`` of any
    source model that supports it.
    """

    user_id = "user_id"
    email = "email"
    roles = "roles"


class UserData(BaseModel):
    """
    Resolved user identity extracted from the incoming request.

    This model is the single source of truth for what user data looks like
    after extraction — regardless of whether it came from individual headers,
    a JWT token, or a single claims header. All source handlers resolve to
    this model.

    Fields are intentionally kept minimal. Extend :class:`UserDataField`
    and this model together if additional user context is needed.
    """

    user_id: str
    email: str | None = None
    roles: list[str] | None = None

    @field_validator("roles", mode="before")
    @classmethod
    def _parse_roles(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        raise ValueError("Roles must be a list or delimiter-separated string")
