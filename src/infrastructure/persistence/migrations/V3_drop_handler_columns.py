"""V3 迁移：移除内容处理器遗留字段

历史背景：
- handlers / handlers_mode / handler_trace 是已废弃的内容处理器字段，ORM 模型已不再定义
- 旧版本数据库中仍保留这些列；本迁移按 V2 先例使用 ALTER TABLE DROP COLUMN 安全删除
- 如果列不存在（新安装），跳过操作

涉及：
- rsshub_user.handlers
- rsshub_sub.handlers / handlers_mode
- rsshub_push_history.handler_trace
"""

from __future__ import annotations

from ...utils import get_logger

logger = get_logger()

_DROP_PLANS: tuple[tuple[str, str], ...] = (
    ("rsshub_user", "handlers"),
    ("rsshub_sub", "handlers"),
    ("rsshub_sub", "handlers_mode"),
    ("rsshub_push_history", "handler_trace"),
)


async def upgrade(conn) -> None:
    """执行 V3 迁移：删除处理器遗留列。"""

    async def _table_exists(table: str) -> bool:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return result.fetchone() is not None

    async def _column_exists(table: str, column: str) -> bool:
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        return any(str(row[1]) == column for row in result.fetchall())

    for table, column in _DROP_PLANS:
        if not await _table_exists(table):
            logger.info("迁移 V3: %s 表不存在，跳过 %s 列", table, column)
            continue
        if not await _column_exists(table, column):
            logger.info("迁移 V3: %s.%s 列不存在，无需删除", table, column)
            continue
        try:
            await conn.exec_driver_sql(
                f"ALTER TABLE {table} DROP COLUMN {column}"
            )
            logger.info("迁移 V3: 成功删除 %s.%s 列", table, column)
        except Exception as exc:
            logger.error("迁移 V3: 删除 %s.%s 列失败: %s", table, column, exc)
            raise

    logger.info("迁移 V3 完成: 移除内容处理器遗留字段")
