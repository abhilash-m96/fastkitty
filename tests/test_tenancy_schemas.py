"""Unit tests for tenancy-related schema normalization behavior."""

from schemas.tenancy import DatabaseConfig


def test_database_config_builds_uri_when_missing() -> None:
    """Build the database URI from individual connection fields when omitted."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="tenant_db",
    )

    assert (
        config.database_uri
        == "postgresql://db_user:db_password@localhost:5432/tenant_db"
    )


def test_database_config_preserves_explicit_uri() -> None:
    """Keep an explicitly supplied URI instead of recomputing it."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="tenant_db",
        database_uri="sqlite:///custom.db",
    )

    assert config.database_uri == "sqlite:///custom.db"
