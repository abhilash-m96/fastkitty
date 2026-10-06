"""Tenant isolation tests against a REAL PostgreSQL server.

Why this file exists: the rest of the suite uses fakes or SQLite. SQLite has no
``search_path`` and no schemas, so it cannot catch the bugs that matter most for
the schema strategy (connection-level state leaking across pooled connections,
fallback to ``public``, identifier quoting/case folding).

Connection: set ``FASTKITTY_TEST_PG_URL`` (default below). The role needs
CREATEDB. The tests create and drop their own ``fk_test_*`` databases.

Skip vs fail: without a reachable server these tests are SKIPPED locally. In CI
set ``FASTKITTY_REQUIRE_PG=1`` so an unreachable database FAILS the run instead
of silently skipping the most important tests.

Pool size is pinned to 1 so consecutive sessions are guaranteed to reuse the
same physical connection; that is exactly where state leaks show up.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from config.settings import Settings
from db.tenancy_strategy import (
    DatabaseTenancyStrategy,
    RowTenancyStrategy,
    SchemaTenancyStrategy,
    TenantDBContext,
)
from models.base import Base
from models.posts import BlogPost
from schemas.posts import BlogPostCreate
from schemas.tenancy import DatabaseConfig
from services.blog_posts_service import BlogPostsService

PG_URL = make_url(
    os.environ.get(
        "FASTKITTY_TEST_PG_URL", "postgresql://postgres:postgres@localhost:5432"
    )
)
DB_SCHEMA = "fk_test_schema"
DB_ROW = "fk_test_row"
DB_DBMODE = "fk_test_dbmode"


def _async_url(database: str) -> str:
    return PG_URL.set(
        drivername="postgresql+asyncpg", database=database
    ).render_as_string(hide_password=False)


def _cfg(database: str, schema: str | None = None, **kw) -> DatabaseConfig:
    return DatabaseConfig(
        host=PG_URL.host or "localhost",
        port=PG_URL.port or 5432,
        username=PG_URL.username or "postgres",
        password=PG_URL.password or "",
        database_name=database,
        schema_name=schema,
        pool_size=1,
        max_overflow=0,
        **kw,
    )


def _ctx(tenant_id: str, database: str, schema: str | None = None) -> TenantDBContext:
    return TenantDBContext(tenant_id=tenant_id, db_config=_cfg(database, schema))


def _settings(strategy: str) -> Settings:
    return Settings.model_construct(TENANCY_DB_STRATEGY=strategy)


async def _recreate_databases() -> None:
    admin = create_async_engine(_async_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            for name in (DB_SCHEMA, DB_ROW, DB_DBMODE):
                await conn.execute(
                    text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
                )
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await admin.dispose()


@pytest.fixture(scope="module", autouse=True)
def _postgres_databases():
    try:
        asyncio.run(_recreate_databases())
    except Exception as exc:  # connection refused, auth failure, no CREATEDB...
        if os.environ.get("FASTKITTY_REQUIRE_PG") == "1":
            pytest.fail(f"PostgreSQL required but unavailable: {exc!r}")
        pytest.skip(f"PostgreSQL not available for isolation tests: {exc!r}")
    yield


async def _start(strategy):
    await strategy.setup(FastAPI())
    return strategy


# --------------------------------------------------------------------------- #
# Schema strategy
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def schema_env():
    admin = create_async_engine(_async_url(DB_SCHEMA))
    async with admin.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS public.blog_posts"))
        for schema in ("ta", "tb", "tc", "Tenant_X", "tenant_x"):
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        # Migrated tenant schemas
        for schema in ("ta", "tb", "Tenant_X", "tenant_x"):
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await conn.run_sync(Base.metadata.create_all)
        # Created but NOT migrated, plus a shared table in public holding a secret.
        await conn.execute(text('CREATE SCHEMA "tc"'))
        await conn.execute(text("SET LOCAL search_path TO public"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "INSERT INTO public.blog_posts (title, content, author, tenant_id) "
                "VALUES ('PUBLIC-SECRET', 'x', 'someone', 'shared')"
            )
        )
    strategy = await _start(SchemaTenancyStrategy(_settings("schema")))
    try:
        yield strategy
    finally:
        await strategy.teardown()
        await admin.dispose()


_INSERT = (
    "INSERT INTO blog_posts (title, content, author, tenant_id) "
    "VALUES (:t, 'x', 'u', :tid)"
)


async def _titles(session) -> list[str]:
    return [
        r[0]
        for r in (await session.execute(text("SELECT title FROM blog_posts"))).all()
    ]


@pytest.mark.asyncio
async def test_schema_rollback_on_reused_connection_does_not_leak(schema_env):
    async with schema_env.get_session(_ctx("ta", DB_SCHEMA, "ta")) as s:
        await s.execute(text(_INSERT), {"t": "A-post", "tid": "ta"})
        await s.commit()
    async with schema_env.get_session(_ctx("tb", DB_SCHEMA, "tb")) as s:
        await s.execute(text(_INSERT), {"t": "B-post", "tid": "tb"})
        await s.rollback()  # e.g. caught IntegrityError and retried
        assert await _titles(s) == []  # must not fall through to A's schema


@pytest.mark.asyncio
async def test_schema_isolated_across_multiple_commits(schema_env):
    async with schema_env.get_session(_ctx("ta", DB_SCHEMA, "ta")) as s:
        await s.execute(text(_INSERT), {"t": "A1", "tid": "ta"})
        await s.commit()
    async with schema_env.get_session(_ctx("tb", DB_SCHEMA, "tb")) as s:
        await s.execute(text(_INSERT), {"t": "B1", "tid": "tb"})
        await s.commit()
        await s.execute(text(_INSERT), {"t": "B2", "tid": "tb"})
        await s.commit()
        assert sorted(await _titles(s)) == ["B1", "B2"]


@pytest.mark.asyncio
async def test_schema_pooled_connection_returns_with_default_search_path(schema_env):
    async with schema_env.get_session(_ctx("ta", DB_SCHEMA, "ta")) as s:
        await s.execute(text(_INSERT), {"t": "A1", "tid": "ta"})
        await s.commit()
    async with schema_env._shared_entry.engine.connect() as conn:
        search_path = (await conn.execute(text("SHOW search_path"))).scalar()
    assert "ta" not in search_path.replace('"$user"', "")


@pytest.mark.asyncio
async def test_schema_unmigrated_tenant_cannot_read_public_tables(schema_env):
    """A tenant whose schema exists but was never migrated must not silently
    resolve ``blog_posts`` to the shared ``public.blog_posts``."""
    async with schema_env.get_session(_ctx("tc", DB_SCHEMA, "tc")) as s:
        try:
            titles = await _titles(s)
        except Exception:
            return  # "relation does not exist" is the correct, fail-closed outcome
    assert "PUBLIC-SECRET" not in titles


@pytest.mark.asyncio
async def test_schema_mixed_case_names_match_quoted_migration_ddl(schema_env):
    async with schema_env.get_session(_ctx("tx", DB_SCHEMA, "Tenant_X")) as s:
        await s.execute(text(_INSERT), {"t": "MixedCase", "tid": "tx"})
        await s.commit()
    async with schema_env.get_session(_ctx("tx2", DB_SCHEMA, "tenant_x")) as s:
        assert "MixedCase" not in await _titles(s)
    async with schema_env.get_session(_ctx("tx", DB_SCHEMA, "Tenant_X")) as s:
        assert "MixedCase" in await _titles(s)


@pytest.mark.asyncio
async def test_schema_service_create_post_stamps_tenant_id(schema_env):
    async with schema_env.get_session(_ctx("ta", DB_SCHEMA, "ta")) as s:
        post = await BlogPostsService(s).create_post(
            BlogPostCreate(title="svc", content="c"), "ua"
        )
        assert post.tenant_id == "ta"


@pytest.mark.asyncio
async def test_schema_conflict_error_masks_password(schema_env):
    async with schema_env.get_session(_ctx("ta", DB_SCHEMA, "ta")):
        pass  # initialise the shared engine
    other = DatabaseConfig(
        host="otherhost",
        port=5432,
        username="u",
        password="TopSecretPw",
        database_name="d",
    )
    with pytest.raises(ValueError) as exc:
        await schema_env._get_or_create_entry(other, strategy_name="Schema")
    assert "TopSecretPw" not in str(exc.value)


# --------------------------------------------------------------------------- #
# Database strategy
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def dbmode_env():
    admin = create_async_engine(_async_url(DB_DBMODE))
    async with admin.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS blog_posts"))
        await conn.run_sync(Base.metadata.create_all)
    strategy = await _start(DatabaseTenancyStrategy(_settings("database")))
    try:
        yield strategy
    finally:
        await strategy.teardown()
        await admin.dispose()


@pytest.mark.asyncio
async def test_database_service_create_post_stamps_tenant_id(dbmode_env):
    async with dbmode_env.get_session(_ctx("da", DB_DBMODE)) as s:
        post = await BlogPostsService(s).create_post(
            BlogPostCreate(title="svc", content="c"), "ua"
        )
        assert post.tenant_id == "da"


# --------------------------------------------------------------------------- #
# Row strategy
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def row_env():
    admin = create_async_engine(_async_url(DB_ROW))
    async with admin.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS blog_posts"))
        await conn.run_sync(Base.metadata.create_all)
    strategy = await _start(RowTenancyStrategy(_settings("row")))
    for tenant in ("ra", "rb"):
        async with strategy.get_session(_ctx(tenant, DB_ROW)) as s:
            s.add(BlogPost(title=f"{tenant}-1", content="c", author="u"))
            s.add(BlogPost(title=f"{tenant}-2", content="c", author="u"))
            await s.commit()

    async def rows() -> list[tuple[str, str]]:
        async with admin.connect() as conn:
            result = await conn.execute(text("SELECT title, tenant_id FROM blog_posts"))
            return sorted((r[0], r[1]) for r in result.all())

    try:
        yield strategy, rows, admin
    finally:
        await strategy.teardown()
        await admin.dispose()


@pytest.mark.asyncio
async def test_row_bulk_update_only_touches_own_tenant(row_env):
    strategy, rows, _ = row_env
    async with strategy.get_session(_ctx("rb", DB_ROW)) as s:
        result = await s.execute(update(BlogPost).values(title="HACKED"))
        await s.commit()
    assert result.rowcount == 2
    assert [r for r in await rows() if r[1] == "ra"] == [("ra-1", "ra"), ("ra-2", "ra")]


@pytest.mark.asyncio
async def test_row_bulk_delete_only_touches_own_tenant(row_env):
    strategy, rows, _ = row_env
    async with strategy.get_session(_ctx("rb", DB_ROW)) as s:
        result = await s.execute(delete(BlogPost))
        await s.commit()
    assert result.rowcount == 2
    assert [r[1] for r in await rows()] == ["ra", "ra"]


@pytest.mark.asyncio
async def test_row_bulk_insert_cannot_plant_foreign_tenant_rows(row_env):
    strategy, rows, _ = row_env
    async with strategy.get_session(_ctx("rb", DB_ROW)) as s:
        with pytest.raises(ValueError):
            await s.execute(
                insert(BlogPost).values(
                    title="PLANTED", content="c", author="u", tenant_id="ra"
                )
            )
    assert not [r for r in await rows() if r[0] == "PLANTED"]


@pytest.mark.asyncio
async def test_row_session_add_ignores_client_supplied_tenant_id(row_env):
    strategy, rows, _ = row_env
    async with strategy.get_session(_ctx("rb", DB_ROW)) as s:
        s.add(BlogPost(title="MINE", content="c", author="u", tenant_id="ra"))
        await s.commit()
    assert ("MINE", "rb") in await rows()
    assert ("MINE", "ra") not in await rows()


@pytest.mark.asyncio
async def test_row_get_of_foreign_primary_key_returns_none(row_env):
    strategy, _, admin = row_env
    async with admin.connect() as conn:
        foreign_id = (
            await conn.execute(
                text("SELECT id FROM blog_posts WHERE tenant_id='ra' LIMIT 1")
            )
        ).scalar()
    async with strategy.get_session(_ctx("rb", DB_ROW)) as s:
        assert await s.get(BlogPost, foreign_id) is None
        assert (
            await s.scalar(select(BlogPost).where(BlogPost.id == foreign_id))
        ) is None


@pytest.mark.asyncio
async def test_row_merge_onto_foreign_primary_key_cannot_overwrite(row_env):
    strategy, rows, admin = row_env
    async with admin.connect() as conn:
        foreign_id = (
            await conn.execute(
                text("SELECT id FROM blog_posts WHERE tenant_id='ra' LIMIT 1")
            )
        ).scalar()
    async with strategy.get_session(_ctx("rb", DB_ROW)) as s:
        try:
            await s.merge(
                BlogPost(id=foreign_id, title="MERGED", content="c", author="u")
            )
            await s.commit()
        except Exception:
            pass  # a primary-key conflict is an acceptable, fail-closed outcome
    assert not [r for r in await rows() if r[0] == "MERGED" and r[1] == "ra"]
    assert sum(1 for r in await rows() if r[1] == "ra") == 2
