"""持久化层包

提供数据库连接、ORM 模型和仓库实现。
"""

from .database import DatabaseManager, RSSHubBaseModel, get_database
from .feed_repository_impl import FeedRepositoryImpl, get_feed_repository
from .list_repository_impl import ListRepositoryImpl, get_list_repository
from .models import (
    EFFECTIVE_OPTION_KEYS,
    INHERIT_VALUE,
    FeedORM,
    ListBatchORM,
    ListBatchPartItemORM,
    ListBatchPartORM,
    ListORM,
    ListQueueItemORM,
    MigrationRecordORM,
    PushHistoryORM,
    SubORM,
    UserORM,
)
from .push_history_repository_impl import (
    PushHistoryRepositoryImpl,
    get_push_history_repository,
)
from .subscription_repository_impl import (
    SubscriptionRepositoryImpl,
    get_subscription_repository,
)
from .user_repository_impl import UserRepositoryImpl, get_user_repository

__all__ = [
    # Database
    "DatabaseManager",
    "RSSHubBaseModel",
    "get_database",
    # ORM Models
    "FeedORM",
    "INHERIT_VALUE",
    "EFFECTIVE_OPTION_KEYS",
    "ListORM",
    "ListQueueItemORM",
    "ListBatchORM",
    "ListBatchPartORM",
    "ListBatchPartItemORM",
    "MigrationRecordORM",
    "PushHistoryORM",
    "SubORM",
    "UserORM",
    # Repositories
    "FeedRepositoryImpl",
    "get_feed_repository",
    "ListRepositoryImpl",
    "get_list_repository",
    "UserRepositoryImpl",
    "get_user_repository",
    "SubscriptionRepositoryImpl",
    "get_subscription_repository",
    "PushHistoryRepositoryImpl",
    "get_push_history_repository",
]
