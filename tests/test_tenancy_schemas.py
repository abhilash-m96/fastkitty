"""Unit tests for tenancy-related schema behavior."""

from schemas.tenancy import DatabaseConfig


def test_database_config_leaves_uri_empty_when_missing() -> None:
    """Keep the raw schema value empty when no explicit URI is supplied."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="tenant_db",
    )

    assert config.database_uri is None


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
