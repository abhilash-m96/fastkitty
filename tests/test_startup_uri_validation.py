import json
from pathlib import Path
import pytest
from config.settings import Settings
from config.tenancy_strategy_validation import validate_tenancy_strategy_startup


def _write_files(
    tmp_path: Path,
    tenants: list[str],
    secrets_configs: dict[str, dict[str, object]],
) -> tuple[str, str]:
    config_data = {
        tid: {
            "tenant_id": tid,
            "display_name": f"Tenant {tid}",
            "is_active": True,
        }
        for tid in tenants
    }
    secrets_data = {
        tid: {
            "tenant_id": tid,
            "database_config": secrets_configs[tid],
        }
        for tid in tenants
    }
    cfg_file = tmp_path / "tenants_config.json"
    sec_file = tmp_path / "tenants_secrets.json"
    cfg_file.write_text(json.dumps(config_data))
    sec_file.write_text(json.dumps(secrets_data))
    return str(cfg_file), str(sec_file)


# ---------------------------------------------------------------------------
# Database Strategy Startup URI Validation
# ---------------------------------------------------------------------------


def test_database_strategy_startup_rejects_duplicate_database_uris(
    tmp_path: Path,
) -> None:
    """database strategy: database_uri must be unique across all tenants."""
    sentinel_password = "SUPER_SECRET_DB_PASS"
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice", "bob"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "shared_user",
                "password": sentinel_password,
                "database_name": "shared_db",
            },
            "bob": {
                "host": "localhost",
                "port": 5432,
                "username": "shared_user",
                "password": sentinel_password,
                "database_name": "shared_db",
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="database",
    )

    with pytest.raises(ValueError) as exc_info:
        validate_tenancy_strategy_startup(settings)

    err = str(exc_info.value)
    assert "Duplicate database_uri" in err
    assert "alice" in err and "bob" in err
    assert sentinel_password not in err


def test_database_strategy_startup_accepts_distinct_database_uris(
    tmp_path: Path,
) -> None:
    """database strategy: different database_uris are accepted."""
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice", "bob"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "user_a",
                "password": "pass_a",
                "database_name": "db_alice",
            },
            "bob": {
                "host": "localhost",
                "port": 5432,
                "username": "user_b",
                "password": "pass_b",
                "database_name": "db_bob",
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="database",
    )
    validate_tenancy_strategy_startup(settings)


# ---------------------------------------------------------------------------
# Row Strategy Startup URI & Pool Validation
# ---------------------------------------------------------------------------


def test_row_strategy_startup_rejects_differing_database_uris(
    tmp_path: Path,
) -> None:
    """row strategy: all tenants must share identical database_uri."""
    sentinel_password = "SUPER_SECRET_ROW_PASS"
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice", "bob"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": sentinel_password,
                "database_name": "db_alice",
            },
            "bob": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": sentinel_password,
                "database_name": "db_bob",
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="row",
    )

    with pytest.raises(ValueError) as exc_info:
        validate_tenancy_strategy_startup(settings)

    err = str(exc_info.value)
    assert "alice" in err and "bob" in err
    assert sentinel_password not in err


def test_row_strategy_startup_rejects_conflicting_pool_settings(
    tmp_path: Path,
) -> None:
    """row strategy: all tenants must have identical pool settings."""
    sentinel_password = "SUPER_SECRET_POOL_PASS"
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice", "bob"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": sentinel_password,
                "database_name": "shared_db",
                "pool_size": 10,
            },
            "bob": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": sentinel_password,
                "database_name": "shared_db",
                "pool_size": 25,
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="row",
    )

    with pytest.raises(ValueError) as exc_info:
        validate_tenancy_strategy_startup(settings)

    err = str(exc_info.value)
    assert "alice" in err and "bob" in err
    assert "pool settings" in err
    assert sentinel_password not in err


def test_row_strategy_startup_accepts_identical_uri_and_pool_settings(
    tmp_path: Path,
) -> None:
    """row strategy: identical database_uri and pool settings pass."""
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice", "bob"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": "pass",
                "database_name": "shared_db",
                "pool_size": 15,
            },
            "bob": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": "pass",
                "database_name": "shared_db",
                "pool_size": 15,
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="row",
    )
    validate_tenancy_strategy_startup(settings)


# ---------------------------------------------------------------------------
# Schema Strategy Startup URI, Pool & Schema Name Validation
# ---------------------------------------------------------------------------


def test_schema_strategy_startup_rejects_differing_database_uris(
    tmp_path: Path,
) -> None:
    """schema strategy: all tenants must share identical database_uri."""
    sentinel_password = "SUPER_SECRET_SCHEMA_PASS"
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice", "bob"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": sentinel_password,
                "database_name": "db_alice",
                "schema_name": "schema_alice",
            },
            "bob": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": sentinel_password,
                "database_name": "db_bob",
                "schema_name": "schema_bob",
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="schema",
    )

    with pytest.raises(ValueError) as exc_info:
        validate_tenancy_strategy_startup(settings)

    err = str(exc_info.value)
    assert "alice" in err and "bob" in err
    assert sentinel_password not in err


def test_schema_strategy_startup_rejects_conflicting_pool_settings(
    tmp_path: Path,
) -> None:
    """schema strategy: all tenants must have identical pool settings."""
    sentinel_password = "SUPER_SECRET_SCHEMA_POOL_PASS"
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice", "bob"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": sentinel_password,
                "database_name": "shared_db",
                "schema_name": "schema_alice",
                "max_overflow": 5,
            },
            "bob": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": sentinel_password,
                "database_name": "shared_db",
                "schema_name": "schema_bob",
                "max_overflow": 20,
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="schema",
    )

    with pytest.raises(ValueError) as exc_info:
        validate_tenancy_strategy_startup(settings)

    err = str(exc_info.value)
    assert "alice" in err and "bob" in err
    assert "pool settings" in err
    assert sentinel_password not in err


def test_schema_strategy_startup_rejects_case_insensitive_duplicate_schema_names(
    tmp_path: Path,
) -> None:
    """schema strategy: schema_name must be unique case-insensitively."""
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice", "bob"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": "pass",
                "database_name": "shared_db",
                "schema_name": "MY_SCHEMA",
            },
            "bob": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": "pass",
                "database_name": "shared_db",
                "schema_name": "my_schema",
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="schema",
    )

    with pytest.raises(
        ValueError,
        match="Duplicate schema_name 'my_schema' detected: used by both 'alice' and 'bob'",
    ):
        validate_tenancy_strategy_startup(settings)


def test_schema_strategy_startup_rejects_63_byte_truncated_duplicate_schema_names(
    tmp_path: Path,
) -> None:
    """schema strategy: schema_names colliding after 63-byte truncation must be rejected."""
    # 64-char names differing only on character index 63 (0-based)
    prefix_63 = "a" * 63
    schema_1 = prefix_63 + "1"
    schema_2 = prefix_63 + "2"

    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice", "bob"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": "pass",
                "database_name": "shared_db",
                "schema_name": schema_1,
            },
            "bob": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": "pass",
                "database_name": "shared_db",
                "schema_name": schema_2,
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="schema",
    )

    with pytest.raises(
        ValueError,
        match=f"Duplicate schema_name '{schema_2}' detected: used by both 'alice' and 'bob'",
    ):
        validate_tenancy_strategy_startup(settings)


def test_schema_strategy_startup_accepts_valid_shared_config(
    tmp_path: Path,
) -> None:
    """schema strategy: identical database_uri & pool settings with unique schemas pass."""
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice", "bob"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": "pass",
                "database_name": "shared_db",
                "schema_name": "alice_schema",
            },
            "bob": {
                "host": "localhost",
                "port": 5432,
                "username": "user_shared",
                "password": "pass",
                "database_name": "shared_db",
                "schema_name": "bob_schema",
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="schema",
    )
    validate_tenancy_strategy_startup(settings)


def test_database_strategy_startup_rejects_same_host_port_db_with_different_credentials(
    tmp_path: Path,
) -> None:
    """database strategy: same (host, port, database_name) with different users must be rejected."""
    sentinel_pass_alice = "SECRET_PASS_ALICE"
    sentinel_pass_bob = "SECRET_PASS_BOB"
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice", "bob"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "alice_user",
                "password": sentinel_pass_alice,
                "database_name": "shared_cluster_db",
            },
            "bob": {
                "host": "LOCALHOST",  # Test case-insensitivity on host
                "port": 5432,
                "username": "bob_user",
                "password": sentinel_pass_bob,
                "database_name": "shared_cluster_db",
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="database",
    )

    with pytest.raises(ValueError) as exc_info:
        validate_tenancy_strategy_startup(settings)

    err = str(exc_info.value)
    assert "Duplicate database_uri" in err
    assert "alice" in err and "bob" in err
    assert sentinel_pass_alice not in err
    assert sentinel_pass_bob not in err


def test_schema_strategy_startup_rejects_reserved_schema_name_public(
    tmp_path: Path,
) -> None:
    """schema strategy: reserved schema name 'public' must fail fast at startup."""
    sentinel_password = "SUPER_SECRET_PASS"
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "user",
                "password": sentinel_password,
                "database_name": "db",
                "schema_name": "public",
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="schema",
    )

    with pytest.raises(ValueError) as exc_info:
        validate_tenancy_strategy_startup(settings)

    err = str(exc_info.value)
    assert "reserved PostgreSQL schema name" in err
    assert sentinel_password not in err


def test_schema_strategy_startup_rejects_invalid_schema_name_injection(
    tmp_path: Path,
) -> None:
    """schema strategy: invalid SQL identifier schema name must fail fast at startup."""
    sentinel_password = "SUPER_SECRET_PASS"
    cfg_file, sec_file = _write_files(
        tmp_path,
        tenants=["alice"],
        secrets_configs={
            "alice": {
                "host": "localhost",
                "port": 5432,
                "username": "user",
                "password": sentinel_password,
                "database_name": "db",
                "schema_name": "bad-name;drop",
            },
        },
    )
    settings = Settings(
        TENANCY_CONFIG_CONNECTION={"type": "file", "file_path": cfg_file},
        TENANCY_SECRETS_CONNECTION={"type": "file", "file_path": sec_file},
        TENANCY_DB_STRATEGY="schema",
    )

    with pytest.raises(ValueError) as exc_info:
        validate_tenancy_strategy_startup(settings)

    err = str(exc_info.value)
    assert "Invalid schema_name for schema strategy" in err
    assert sentinel_password not in err
