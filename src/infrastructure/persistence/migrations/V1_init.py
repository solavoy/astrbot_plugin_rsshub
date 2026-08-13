"""V1 初始化迁移（唯一 baseline）

不兼容重构后数据库迁移只有这一个 baseline，直接在全新库上建出最新 schema：
- rsshub_user / rsshub_feed / rsshub_sub / rsshub_push_history / rsshub_migration_record
- List 聚合五表：rsshub_lists / rsshub_list_queue_items / rsshub_list_batches /
  rsshub_list_batch_parts / rsshub_list_batch_part_items
- 订阅扩展列：list_id / include_keywords / exclude_keywords

已移除的历史列：style / handlers / handlers_mode / handler_trace / link_preview /
needs_binding_notice / 翻译缓存表。旧库需重建（不兼容升级）。
"""

from __future__ import annotations

from ...utils import get_logger

logger = get_logger()


async def upgrade(conn) -> None:
    """执行 V1 初始化迁移（幂等：表存在则跳过）。"""

    async def _table_exists(table: str) -> bool:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return result.fetchone() is not None

    async def _create_table(table: str, sql: str) -> None:
        if not await _table_exists(table):
            await conn.exec_driver_sql(sql)
            logger.info("迁移 V1: 创建表 %s", table)

    # 1. 用户表
    await _create_table(
        "rsshub_user",
        """
        CREATE TABLE rsshub_user (
            id VARCHAR PRIMARY KEY,
            state INTEGER NOT NULL DEFAULT 1,
            interval INTEGER NOT NULL DEFAULT -100,
            notify INTEGER NOT NULL DEFAULT -100,
            send_mode INTEGER NOT NULL DEFAULT -100,
            length_limit INTEGER NOT NULL DEFAULT -100,
            display_author INTEGER NOT NULL DEFAULT -100,
            display_via INTEGER NOT NULL DEFAULT -100,
            display_title INTEGER NOT NULL DEFAULT -100,
            display_entry_tags INTEGER NOT NULL DEFAULT -100,
            display_media INTEGER NOT NULL DEFAULT -100,
            default_target_session TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )

    # 2. Feed 表
    await _create_table(
        "rsshub_feed",
        """
        CREATE TABLE rsshub_feed (
            id INTEGER PRIMARY KEY,
            state INTEGER NOT NULL DEFAULT 1,
            link VARCHAR(4096) NOT NULL UNIQUE,
            title VARCHAR(1024) NOT NULL,
            entry_hashes JSON,
            etag VARCHAR(128),
            last_modified DATETIME,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )

    # 3. 订阅表（含 List 扩展列）
    await _create_table(
        "rsshub_sub",
        """
        CREATE TABLE rsshub_sub (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state INTEGER NOT NULL DEFAULT 1,
            user_id VARCHAR NOT NULL,
            feed_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            target_session TEXT,
            platform_name TEXT,
            interval INTEGER NOT NULL DEFAULT -100,
            next_check_time DATETIME,
            notify INTEGER NOT NULL DEFAULT -100,
            send_mode INTEGER NOT NULL DEFAULT -100,
            length_limit INTEGER NOT NULL DEFAULT -100,
            display_author INTEGER NOT NULL DEFAULT -100,
            display_via INTEGER NOT NULL DEFAULT -100,
            display_title INTEGER NOT NULL DEFAULT -100,
            display_entry_tags INTEGER NOT NULL DEFAULT -100,
            display_media INTEGER NOT NULL DEFAULT -100,
            list_id INTEGER,
            include_keywords JSON,
            exclude_keywords JSON,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES rsshub_user (id),
            FOREIGN KEY (feed_id) REFERENCES rsshub_feed (id),
            FOREIGN KEY (list_id) REFERENCES rsshub_lists (id)
        )
        """,
    )

    # 4. 推送历史表（含 agent push 兼容列）
    await _create_table(
        "rsshub_push_history",
        """
        CREATE TABLE rsshub_push_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sub_id INTEGER,
            user_id VARCHAR NOT NULL,
            feed_id INTEGER,
            source_type VARCHAR(16) NOT NULL DEFAULT 'feed',
            source_key VARCHAR(255),
            content VARCHAR NOT NULL DEFAULT '',
            raw_xml TEXT,
            media_urls JSON,
            entry_title VARCHAR(1024) NOT NULL DEFAULT '',
            entry_link VARCHAR(4096) NOT NULL DEFAULT '',
            entry_guid VARCHAR(512),
            feed_title VARCHAR(1024) NOT NULL DEFAULT '',
            feed_link VARCHAR(4096) NOT NULL DEFAULT '',
            platform_name VARCHAR(64),
            target_session VARCHAR(255),
            status VARCHAR(16),
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            fail_reason VARCHAR(512),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            FOREIGN KEY (sub_id) REFERENCES rsshub_sub (id),
            FOREIGN KEY (user_id) REFERENCES rsshub_user (id),
            FOREIGN KEY (feed_id) REFERENCES rsshub_feed (id)
        )
        """,
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_rsshub_push_history_scope_guid "
        "ON rsshub_push_history (source_type, user_id, target_session, source_key, entry_guid, status)"
    )

    # 5. 迁移记录表
    await _create_table(
        "rsshub_migration_record",
        """
        CREATE TABLE rsshub_migration_record (
            version VARCHAR(32) PRIMARY KEY,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            description VARCHAR(256)
        )
        """,
    )

    # 6. List 表
    await _create_table(
        "rsshub_lists",
        """
        CREATE TABLE rsshub_lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            target_session VARCHAR(255) NOT NULL,
            platform_name VARCHAR(64) NOT NULL DEFAULT '',
            state INTEGER NOT NULL DEFAULT 1,
            batch_size INTEGER NOT NULL DEFAULT 10,
            max_wait_minutes INTEGER NOT NULL DEFAULT 120,
            content_mode VARCHAR(16) NOT NULL DEFAULT 'full',
            full_delivery_mode VARCHAR(16) NOT NULL DEFAULT 'split',
            ai_summary_enabled BOOLEAN NOT NULL DEFAULT 0,
            ai_summary_prompt VARCHAR(4096) NOT NULL DEFAULT '',
            include_keywords JSON,
            exclude_keywords JSON,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES rsshub_user (id)
        )
        """,
    )
    await _create_table(
        "rsshub_list_queue_items",
        """
        CREATE TABLE rsshub_list_queue_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            list_id INTEGER NOT NULL,
            sub_id INTEGER NOT NULL,
            feed_id INTEGER NOT NULL,
            push_history_id INTEGER NOT NULL,
            entry_key VARCHAR(1024) NOT NULL,
            entry_title VARCHAR(1024) NOT NULL DEFAULT '',
            entry_link VARCHAR(4096) NOT NULL DEFAULT '',
            feed_title VARCHAR(1024) NOT NULL DEFAULT '',
            feed_link VARCHAR(4096) NOT NULL DEFAULT '',
            markdown_content TEXT NOT NULL DEFAULT '',
            media_items JSON,
            queued_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            batch_id INTEGER,
            state VARCHAR(16) NOT NULL DEFAULT 'queued',
            FOREIGN KEY (list_id) REFERENCES rsshub_lists (id),
            FOREIGN KEY (sub_id) REFERENCES rsshub_sub (id),
            FOREIGN KEY (feed_id) REFERENCES rsshub_feed (id)
        )
        """,
    )
    await conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_list_queue_item "
        "ON rsshub_list_queue_items (list_id, sub_id, entry_key)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_list_queue_items_state "
        "ON rsshub_list_queue_items (list_id, state, queued_at)"
    )
    await _create_table(
        "rsshub_list_batches",
        """
        CREATE TABLE rsshub_list_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            list_id INTEGER NOT NULL,
            state VARCHAR(16) NOT NULL DEFAULT 'preparing',
            item_count INTEGER NOT NULL DEFAULT 0,
            summary_markdown TEXT NOT NULL DEFAULT '',
            summary_status VARCHAR(16) NOT NULL DEFAULT 'disabled',
            fail_reason TEXT NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at DATETIME,
            completed_at DATETIME,
            FOREIGN KEY (list_id) REFERENCES rsshub_lists (id)
        )
        """,
    )
    await _create_table(
        "rsshub_list_batch_parts",
        """
        CREATE TABLE rsshub_list_batch_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            sequence INTEGER NOT NULL DEFAULT 0,
            kind VARCHAR(16) NOT NULL,
            markdown_content TEXT NOT NULL DEFAULT '',
            media_items JSON,
            state VARCHAR(16) NOT NULL DEFAULT 'pending',
            fail_reason TEXT NOT NULL DEFAULT '',
            sent_at DATETIME,
            FOREIGN KEY (batch_id) REFERENCES rsshub_list_batches (id),
            UNIQUE (batch_id, sequence)
        )
        """,
    )
    await _create_table(
        "rsshub_list_batch_part_items",
        """
        CREATE TABLE rsshub_list_batch_part_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_part_id INTEGER NOT NULL,
            queue_item_id INTEGER NOT NULL,
            FOREIGN KEY (batch_part_id) REFERENCES rsshub_list_batch_parts (id),
            FOREIGN KEY (queue_item_id) REFERENCES rsshub_list_queue_items (id),
            UNIQUE (batch_part_id, queue_item_id)
        )
        """,
    )

    logger.info("迁移 V1 完成: 初始化最新数据库 schema")
