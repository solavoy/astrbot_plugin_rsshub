from __future__ import annotations

import pytest
from astrbot_plugin_rsshub.src.infrastructure.persistence.database import (
    DatabaseManager,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.migrations import (
    MigrationRunner,
)
from sqlalchemy.ext.asyncio import create_async_engine


def test_database_is_initialized_requires_session_maker():
    db = DatabaseManager()
    db._engine = object()
    db._session_maker = None

    assert db.is_initialized is False


@pytest.mark.asyncio
async def test_migration_runner_only_discovers_single_baseline():
    runner = MigrationRunner()

    assert [(item.version, item.name) for item in runner.scripts] == [
        (1, "V1_init"),
    ]


@pytest.mark.asyncio
async def test_v1_baseline_creates_full_current_schema():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        executed = await MigrationRunner().run_all(conn)

        assert executed == [1]

        sub_columns = {
            str(row[1])
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(rsshub_sub)")
            ).fetchall()
        }
        user_columns = {
            str(row[1])
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(rsshub_user)")
            ).fetchall()
        }
        history_columns = {
            str(row[1])
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(rsshub_push_history)")
            ).fetchall()
        }
        indexes = {
            str(row[0])
            for row in (
                await conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            ).fetchall()
        }

        # 已移除的历史列
        assert "style" not in sub_columns and "style" not in user_columns
        assert "handlers_mode" not in sub_columns
        assert "handlers" not in user_columns
        assert "link_preview" not in sub_columns
        assert "link_preview" not in user_columns
        assert "needs_binding_notice" not in user_columns
        # 保留的关键列
        assert {"source_type", "source_key", "raw_xml"}.issubset(history_columns)
        assert {"list_id", "include_keywords", "exclude_keywords"}.issubset(
            sub_columns
        )
        assert "idx_rsshub_push_history_scope_guid" in indexes

        # List 五表
        tables = {
            str(row[0])
            for row in (
                await conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            ).fetchall()
        }
        for t in (
            "rsshub_lists",
            "rsshub_list_queue_items",
            "rsshub_list_batches",
            "rsshub_list_batch_parts",
            "rsshub_list_batch_part_items",
        ):
            assert t in tables

    await engine.dispose()
