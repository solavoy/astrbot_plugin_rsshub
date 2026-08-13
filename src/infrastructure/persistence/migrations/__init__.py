"""数据库迁移包

提供版本化数据库迁移功能。
迁移脚本命名规范: V{数字}_{描述}.py
当前只有一个 baseline：V1_init.py（最新 schema，幂等建表）。
"""

from .migration_runner import MigrationRunner, run_migrations

__all__ = [
    "MigrationRunner",
    "run_migrations",
]
