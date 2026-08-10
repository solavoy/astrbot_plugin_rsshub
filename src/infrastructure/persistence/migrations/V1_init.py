"""V1 初始化迁移

创建基础数据库表结构：
- rsshub_user: 用户表
- rsshub_feed: Feed 表
- rsshub_sub: 订阅表
- rsshub_push_history: 推送历史表
- rsshub_migration_record: 迁移记录表
"""

from __future__ import annotations

from ...utils import get_logger

logger = get_logger()


async def upgrade(conn) -> None:
    """执行 V1 初始化迁移"""

    async def _table_exists(table: str) -> bool:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return result.fetchone() is not None

    async def _column_exists(table: str, column: str) -> bool:
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        return any(str(row[1]) == column for row in result.fetchall())

    async def _index_exists(index_name: str) -> bool:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        )
        return result.fetchone() is not None

    # 创建 rsshub_user 表
    if not await _table_exists("rsshub_user"):
        await conn.exec_driver_sql(
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
                style INTEGER NOT NULL DEFAULT -100,
                display_media INTEGER NOT NULL DEFAULT -100,
                default_target_session TEXT,
                needs_binding_notice INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        logger.info("迁移 V1: 创建 rsshub_user 表")

    # 创建 rsshub_feed 表
    if not await _table_exists("rsshub_feed"):
        await conn.exec_driver_sql(
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
            """
        )
        logger.info("迁移 V1: 创建 rsshub_feed 表")

    # 创建 rsshub_sub 表
    if not await _table_exists("rsshub_sub"):
        await conn.exec_driver_sql(
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
                style INTEGER NOT NULL DEFAULT -100,
                display_media INTEGER NOT NULL DEFAULT -100,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES rsshub_user (id),
                FOREIGN KEY (feed_id) REFERENCES rsshub_feed (id)
            )
            """
        )
        logger.info("迁移 V1: 创建 rsshub_sub 表")

    # 创建 rsshub_push_history 表
    if not await _table_exists("rsshub_push_history"):
        await conn.exec_driver_sql(
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
            """
        )
        logger.info("迁移 V1: 创建 rsshub_push_history 表")

    if not await _column_exists("rsshub_push_history", "source_type"):
        await conn.exec_driver_sql(
            """
            ALTER TABLE rsshub_push_history
            ADD COLUMN source_type VARCHAR(16) NOT NULL DEFAULT 'feed'
            """
        )
        logger.info("迁移 V1: 为 rsshub_push_history 添加 source_type 字段")

    if not await _column_exists("rsshub_push_history", "source_key"):
        await conn.exec_driver_sql(
            """
            ALTER TABLE rsshub_push_history
            ADD COLUMN source_key VARCHAR(255)
            """
        )
        logger.info("迁移 V1: 为 rsshub_push_history 添加 source_key 字段")

    if not await _column_exists("rsshub_push_history", "raw_xml"):
        await conn.exec_driver_sql(
            """
            ALTER TABLE rsshub_push_history
            ADD COLUMN raw_xml TEXT
            """
        )
        logger.info("迁移 V1: 为 rsshub_push_history 添加 raw_xml 字段")

    if not await _index_exists("idx_rsshub_push_history_scope_guid"):
        await conn.exec_driver_sql(
            """
            CREATE INDEX idx_rsshub_push_history_scope_guid
            ON rsshub_push_history (source_type, user_id, target_session, source_key, entry_guid, status)
            """
        )
        logger.info("迁移 V1: 创建 rsshub_push_history 作用域去重索引")

    # 创建迁移记录表
    if not await _table_exists("rsshub_migration_record"):
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_migration_record (
                version VARCHAR(32) PRIMARY KEY,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                description VARCHAR(256)
            )
            """
        )
        logger.info("迁移 V1: 创建 rsshub_migration_record 表")

    logger.info("迁移 V1 完成: 初始化数据库表")
