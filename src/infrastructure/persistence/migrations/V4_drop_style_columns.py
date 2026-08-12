"""V4 迁移：删除 rsshub_sub 与 rsshub_user 的 style 列。

统一发送模型移除了 style 排版配置；旧列删除，列不存在时跳过（幂等）。
"""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    """删除 style 列；列已不存在时保持幂等。"""
    for table in ("rsshub_sub", "rsshub_user"):
        cols = [
            str(row[1])
            for row in (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
        ]
        if "style" in cols:
            await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN style"))
