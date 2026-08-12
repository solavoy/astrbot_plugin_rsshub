"""数据库迁移包

提供版本化数据库迁移功能。
迁移脚本命名规范: V{数字}_{描述}.py
"""

from .migration_runner import (
    MigrationRunner,
    cleanup_legacy_translation_tables,
    ensure_push_history_schema,
    ensure_user_rows,
    run_migrations,
)
from .V4_drop_style_columns import upgrade as V4_drop_style_columns
from .V5_create_list_batching import upgrade as V5_create_list_batching

__all__ = [
    "MigrationRunner",
    "V4_drop_style_columns",
    "V5_create_list_batching",
    "cleanup_legacy_translation_tables",
    "ensure_push_history_schema",
    "ensure_user_rows",
    "run_migrations",
]
