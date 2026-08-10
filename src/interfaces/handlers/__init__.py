"""命令处理器模块（纯函数）"""

from .admin import handle_test_sub
from .batch import (
    handle_batch_activate,
    handle_batch_deactivate,
    handle_unsub_all,
)
from .config import (
    handle_sub_get_session,
    handle_sub_get_user,
    handle_sub_profile_get,
    handle_sub_profile_set,
    handle_sub_set,
    handle_sub_set_session,
    handle_sub_set_user,
)
from .data import handle_export, handle_import
from .subscription import (
    handle_rss_stop,
    handle_sub,
    handle_sub_list,
    handle_sub_state,
    handle_sub_status,
    handle_unsub,
)

__all__ = [
    "handle_sub",
    "handle_unsub",
    "handle_sub_list",
    "handle_rss_stop",
    "handle_sub_status",
    "handle_sub_state",
    "handle_sub_profile_set",
    "handle_sub_profile_get",
    "handle_sub_set",
    "handle_sub_set_user",
    "handle_sub_get_user",
    "handle_sub_set_session",
    "handle_sub_get_session",
    "handle_batch_activate",
    "handle_batch_deactivate",
    "handle_unsub_all",
    "handle_export",
    "handle_import",
    "handle_test_sub",
]
