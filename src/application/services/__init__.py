"""应用服务包的兼容导出层。

优先从具体模块导入，避免包导入时拉起整片实现。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MAP = {
    "AgentXmlPushService": "agent_xml_push_service",
    "AgentXmlValidationError": "agent_xml_push_service",
    "FeedPollingService": "feed_polling_service",
    "FeedPollingResult": "feed_polling_service",
    "FeedReadResult": "feed_polling_service",
    "ListQueueService": "list_queue_service",
    "EnqueueResult": "list_queue_service",
    "ListBatchCoordinator": "list_batch_coordinator",
    "ListBatchRenderer": "list_batch_renderer",
    "AstrBotAiSummaryProvider": "ai_summary_service",
    "normalize_ai_markdown": "ai_summary_service",
    "NotificationDispatcher": "notification_dispatcher",
    "SessionPushQueue": "session_push_queue",
    "PushJob": "session_push_queue",
    "PushJobResult": "session_push_queue",
    "StopPushJobResult": "session_push_queue",
    "SubscriptionFilterService": "subscription_filter_service",
    "FilterResult": "subscription_filter_service",
    "HTMLParser": "html_parser",
    "HTMLCleaner": "html_parser",
    "parse_html": "html_parser",
    "clean_html": "html_parser",
    "serialize_subscriptions_to_toml": "subscription_serializer",
    "parse_subscriptions_toml": "subscription_serializer",
    "SubscriptionImportPayload": "subscription_serializer",
    "ImportSubscriptionRecord": "subscription_serializer",
}

__all__ = sorted(_EXPORT_MAP)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MAP.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
