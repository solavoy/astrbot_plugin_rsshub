"""通知服务实现

将 RSS 调度器的通知请求桥接到应用层的通知分发服务。
实现 schedule.rss_scheduler.NotificationService 协议。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...application.ports import MessageSenderProvider
from ...application.services.notification_dispatcher import (
    NotificationDispatcher,
    SendTarget,
)
from ...application.services.session_push_queue import SessionPushQueue
from ...domain.entities.content_types import EntryContentContext
from ...domain.repositories.push_history_repository import PushHistoryRepository
from ...domain.repositories.subscription_repository import SubscriptionRepository
from ..pipeline import EffectivePushOptions, EntryFormatInput, EntryTextFormatter
from ..utils import get_logger
from .senders.provider import InfrastructureMessageSenderProvider

if TYPE_CHECKING:
    from ...domain.entities.feed import Feed
    from ...domain.entities.subscription import Subscription

logger = get_logger()
_entry_text_formatter = EntryTextFormatter()


def _entry_get(entry: Any, key: str, default: Any = None) -> Any:
    if hasattr(entry, "get"):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _entry_text(entry: Any, *keys: str) -> str:
    for key in keys:
        value = _entry_get(entry, key)
        if value is None:
            continue
        return str(value)
    return ""


def _entry_raw_xml(entry: Any) -> str:
    for key in ("raw_xml", "raw", "xml"):
        value = _entry_get(entry, key)
        if value is None:
            continue
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").strip()
        raw_xml = str(value).strip()
        if raw_xml:
            return raw_xml
    return ""


class NotificationServiceImpl:
    """通知服务实现

    实现 RSSScheduler 所需的 NotificationService 协议。
    将调度器的通知桥接到应用层 NotificationDispatcher。
    """

    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
        push_history_repo: PushHistoryRepository,
        sender_provider: MessageSenderProvider | None = None,
        push_job_queue: SessionPushQueue | None = None,
    ):
        self._sender_provider = sender_provider or InfrastructureMessageSenderProvider()
        self._push_job_queue = push_job_queue or SessionPushQueue()
        self._dispatcher = NotificationDispatcher(
            subscription_repo=subscription_repo,
            push_history_repo=push_history_repo,
            sender_provider=self._sender_provider,
            push_job_queue=self._push_job_queue,
        )

    async def notify_feed_update(
        self,
        feed: Feed,
        subscriptions: list[Subscription],
        entries: list[dict[str, Any]],
    ) -> bool:
        """通知订阅者 Feed 更新

        Args:
            feed: 更新的 Feed
            subscriptions: 相关订阅列表
            entries: 新条目列表（feedparser 原始条目）

        Returns:
            是否全部成功
        """
        success_count = 0
        total_count = 0

        for entry in entries:
            entry_title = _entry_text(entry, "title")
            entry_link = _entry_text(entry, "link", "guid")
            entry_guid = _entry_text(entry, "guid", "id")
            summary = _entry_text(entry, "summary", "description")
            entry_content = _entry_text(entry, "content", "content_encoded")
            author = _entry_text(entry, "author")
            raw_xml = _entry_raw_xml(entry)

            media_urls: list[str] = []
            media_content = (
                _entry_get(entry, "media_content")
                or _entry_get(entry, "enclosures")
                or []
            )
            for mc in media_content:
                url = _entry_get(mc, "url") or _entry_get(mc, "href") or ""
                if url:
                    media_urls.append(str(url))

            content = await _entry_text_formatter.format_entry(
                EntryFormatInput(
                    title=entry_title,
                    content=entry_content or summary,
                    summary=summary,
                    link=entry_link,
                    author=author,
                    feed_title=feed.title,
                    feed_link=feed.link,
                    tags=tuple(_entry_get(entry, "tags", []) or ()),
                ),
                EffectivePushOptions(),
            )
            clean_body = await _entry_text_formatter.clean_text(
                entry_content or summary
            )

            stats = await self._dispatcher.dispatch_to_feed_subscribers(
                feed_id=feed.id if feed.id else 0,
                content=content,
                entry_title=entry_title,
                entry_link=entry_link,
                feed_title=feed.title,
                feed_link=feed.link,
                media_urls=media_urls,
                entry_guid=entry_guid,
                raw_entry=EntryContentContext(
                    title=entry_title,
                    summary=clean_body,
                    content=clean_body,
                    link=entry_link,
                    author=author,
                    feed_title=feed.title,
                    feed_link=feed.link,
                    raw_xml=raw_xml,
                    media_urls=tuple(media_urls),
                ),
            )
            success_count += stats.get("success", 0)
            total_count += (
                stats.get("success", 0)
                + stats.get("failed", 0)
                + stats.get("pending", 0)
            )

        if total_count > 0:
            logger.info(
                "Feed 通知完成: feed=%s, success=%s/%s",
                feed.link,
                success_count,
                total_count,
            )

        return success_count == total_count if total_count > 0 else True

    async def notify_feed_error(
        self,
        feed: Feed,
        subscriptions: list[Subscription],
        error: str,
    ) -> None:
        """通知订阅者 Feed 错误

        Args:
            feed: 出错的 Feed
            subscriptions: 相关订阅列表
            error: 错误描述
        """
        logger.warning(
            "Feed 抓取错误: feed=%s, subscriptions=%d, error=%s",
            feed.link,
            len(subscriptions),
            error,
        )
        content = f"⚠️ Feed 抓取失败: {feed.title or feed.link}\n错误: {error}"

        for sub in subscriptions:
            if not sub.target_session:
                continue

            await self._dispatcher.send_to_session(
                target=SendTarget(
                    user_id=sub.user_id,
                    platform_name=sub.platform_name,
                    target_session=sub.target_session,
                    sub_id=sub.id,
                ),
                content=content,
                media_urls=None,
                job_description=f"feed-error feed={feed.id}, sub={sub.id}",
            )


_notification_service_instance: NotificationServiceImpl | None = None


def get_notification_service(
    subscription_repo: SubscriptionRepository | None = None,
    push_history_repo: PushHistoryRepository | None = None,
    sender_provider: MessageSenderProvider | None = None,
    push_job_queue: SessionPushQueue | None = None,
) -> NotificationServiceImpl:
    """获取通知服务实例

    Args:
        subscription_repo: 订阅仓库（首次调用时必须提供）
        push_history_repo: 推送历史仓库（首次调用时必须提供）

    Returns:
        NotificationServiceImpl 实例
    """
    global _notification_service_instance
    if _notification_service_instance is None:
        if subscription_repo is None or push_history_repo is None:
            raise RuntimeError(
                "首次获取 NotificationService 时必须提供 subscription_repo 和 push_history_repo"
            )
        _notification_service_instance = NotificationServiceImpl(
            subscription_repo=subscription_repo,
            push_history_repo=push_history_repo,
            sender_provider=sender_provider,
            push_job_queue=push_job_queue,
        )
    return _notification_service_instance


def reset_notification_service() -> None:
    """重置通知服务（主要用于测试）"""
    global _notification_service_instance
    _notification_service_instance = None
