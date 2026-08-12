"""V5 迁移：创建 List 批次表并扩展订阅列

新增 List 聚合推送所需的表：
- rsshub_lists：List 逻辑集合
- rsshub_list_queue_items：待发送队列项
- rsshub_list_batches：批次
- rsshub_list_batch_parts：批次分片
- rsshub_list_batch_part_items：分片与队列项关联

同时给 rsshub_sub 增加 list_id / include_keywords / exclude_keywords 列。
所有操作幂等：表存在则跳过，列缺失才添加。
"""

from __future__ import annotations

from ...utils import get_logger

logger = get_logger()


async def _table_exists(conn, table: str) -> bool:
    result = await conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return result.fetchone() is not None


async def _column_exists(conn, table: str, column: str) -> bool:
    result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    return any(str(row[1]) == column for row in result.fetchall())


async def _create_table(conn, table: str, sql: str) -> None:
    if not await _table_exists(conn, table):
        await conn.exec_driver_sql(sql)
        logger.info("迁移 V5: 创建表 %s", table)


async def upgrade(conn) -> None:
    """执行 V5 迁移：创建 List 批次表并扩展订阅列。"""

    # 1. rsshub_lists
    await _create_table(
        conn,
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

    # 2. rsshub_list_queue_items
    await _create_table(
        conn,
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

    # 3. rsshub_list_batches
    await _create_table(
        conn,
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

    # 4. rsshub_list_batch_parts
    await _create_table(
        conn,
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

    # 5. rsshub_list_batch_part_items
    await _create_table(
        conn,
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

    # 6. rsshub_sub 扩展列
    if await _table_exists(conn, "rsshub_sub"):
        if not await _column_exists(conn, "rsshub_sub", "list_id"):
            await conn.exec_driver_sql(
                "ALTER TABLE rsshub_sub ADD COLUMN list_id INTEGER"
            )
            logger.info("迁移 V5: rsshub_sub 增加 list_id 列")
        if not await _column_exists(conn, "rsshub_sub", "include_keywords"):
            await conn.exec_driver_sql(
                "ALTER TABLE rsshub_sub ADD COLUMN include_keywords JSON"
            )
            logger.info("迁移 V5: rsshub_sub 增加 include_keywords 列")
        if not await _column_exists(conn, "rsshub_sub", "exclude_keywords"):
            await conn.exec_driver_sql(
                "ALTER TABLE rsshub_sub ADD COLUMN exclude_keywords JSON"
            )
            logger.info("迁移 V5: rsshub_sub 增加 exclude_keywords 列")

    logger.info("迁移 V5 完成: 创建 List 批次表并扩展订阅列")
