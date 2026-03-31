"""Unit tests for tenancy-related schema behavior."""

from schemas.tenancy import DatabaseConfig


def test_database_config_builds_uri_from_fields() -> None:
    """Compose a postgresql+asyncpg URI from discrete fields when no URI is supplied."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="tenant_db",
    )

    assert (
        config.database_uri
        == "postgresql+asyncpg://db_user:db_password@localhost:5432/tenant_db"
    )


def test_database_config_normalises_postgresql_scheme() -> None:
    """Rewrite postgresql:// scheme to postgresql+asyncpg:// on a supplied URI."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="tenant_db",
        database_uri="postgresql://db_user:db_password@localhost:5432/tenant_db",
    )

    assert (
        config.database_uri
        == "postgresql+asyncpg://db_user:db_password@localhost:5432/tenant_db"
    )


def test_database_config_normalises_postgres_shorthand_scheme() -> None:
    """Rewrite postgres:// shorthand scheme to postgresql+asyncpg://."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="tenant_db",
        database_uri="postgres://db_user:db_password@localhost:5432/tenant_db",
    )

    assert (
        config.database_uri
        == "postgresql+asyncpg://db_user:db_password@localhost:5432/tenant_db"
    )


def test_database_config_preserves_already_normalised_uri() -> None:
    """Leave a postgresql+asyncpg:// URI untouched."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="tenant_db",
        database_uri="postgresql+asyncpg://db_user:db_password@localhost:5432/tenant_db",
    )

    assert (
        config.database_uri
        == "postgresql+asyncpg://db_user:db_password@localhost:5432/tenant_db"
    )


def test_database_config_normalises_dialect_field() -> None:
    """Normalise the dialect field to postgresql+asyncpg regardless of input."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="tenant_db",
    )

    assert config.dialect == "postgresql+asyncpg"


def test_database_config_preserves_non_postgresql_uri() -> None:
    """Leave non-postgresql URIs untouched — other drivers are user-managed."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="tenant_db",
        database_uri="sqlite:///custom.db",
    )

    assert config.database_uri == "sqlite:///custom.db"


def test_database_config_preserves_schema_name() -> None:
    """Keep the schema name available for schema-per-tenant validation."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="tenant_db",
        schema_name="tenant_one",
    )

    assert config.schema_name == "tenant_one"
