"""List 聚合推送端到端集成测试。

覆盖真实链路：建 List + 订阅(list_id) → poll_feed_group → 持久化入队 →
coordinator.tick 触发批次 → 渲染标题链接 → 发送分片 → 水位确认推进。
"""

from __future__ import annotations

from types import SimpleNamespace

import feedparser
import pytest

from astrbot_plugin_rsshub.src.application.dto.web_feed_dto import WebFeed
from astrbot_plugin_rsshub.src.application.ports import SendResult
from astrbot_plugin_rsshub.src.application.services.feed_polling_service import (
    FeedPollingService,
)
from astrbot_plugin_rsshub.src.application.services.list_batch_coordinator import (
    ListBatchCoordinator,
)
from astrbot_plugin_rsshub.src.application.services.list_batch_renderer import (
    ListBatchRenderer,
)
from astrbot_plugin_rsshub.src.application.services.list_queue_service import (
    ListQueueService,
)
from astrbot_plugin_rsshub.src.application.services.notification_dispatcher import (
    NotificationDispatcher,
)
from astrbot_plugin_rsshub.src.application.services.session_push_queue import (
    SessionPushQueue,
)
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.domain.entities.list_entities import ListEntity
from astrbot_plugin_rsshub.src.domain.entities.subscription import Subscription
from astrbot_plugin_rsshub.src.infrastructure.persistence.database import get_database
from astrbot_plugin_rsshub.src.infrastructure.persistence.feed_repository_impl import (
    FeedRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.list_repository_impl import (
    ListRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.push_history_repository_impl import (
    PushHistoryRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.subscription_repository_impl import (
    SubscriptionRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.user_repository_impl import (
    UserRepositoryImpl,
)


class _RecordingSender:
    """记录每次发送的假 sender。"""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_to_user(self, request, context=None):
        self.messages.append(str(request.message or ""))
        return SendResult(ok=True)


class _SenderProvider:
    def __init__(self, sender: _RecordingSender) -> None:
        self._sender = sender

    def get(self, platform_name: str | None):
        return self._sender


class _ContentBox:
    """可变内容持有者，供测试在两次轮询间追加新条目。"""

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeFetcher:
    def __init__(self, box: _ContentBox) -> None:
        self._box = box

    async def fetch(self, url: str, **kwargs):
        parsed = feedparser.parse(self._box.content)
        return WebFeed(
            url=url,
            content=self._box.content.encode("utf-8"),
            status=200,
            rss_d=parsed,
        )

    async def close(self) -> None:
        pass


def _fetcher_factory(box: _ContentBox):
    def factory(*, timeout: int = 30, proxy: str = ""):
        return _FakeFetcher(box)
    return factory


@pytest.mark.asyncio
async def test_list_push_end_to_end(temp_db_path, sample_rss_feed):
    await get_database().init(str(temp_db_path))

    feed_repo = FeedRepositoryImpl()
    sub_repo = SubscriptionRepositoryImpl()
    user_repo = UserRepositoryImpl()
    hist_repo = PushHistoryRepositoryImpl()
    list_repo = ListRepositoryImpl()

    user = await user_repo.get_or_create("u1")
    feed = await feed_repo.save(
        Feed(link="https://rsshub.app/v2ex/topics/latest", title="V2EX", state=1)
    )
    lst = await list_repo.save_list(
        ListEntity(
            name="Tech",
            user_id=user.id,
            target_session="telegram:Group:1",
            platform_name="telegram",
            batch_size=1,
            max_wait_minutes=0,
            content_mode="title_link",
        )
    )
    sub = await sub_repo.save(
        Subscription(
            user_id=user.id,
            feed_id=feed.id,
            target_session="telegram:Group:1",
            platform_name="telegram",
            list_id=lst.id,
            notify=1,
            send_mode=0,
            state=1,
        )
    )

    queue = SessionPushQueue()
    sender = _RecordingSender()
    list_queue_service = ListQueueService(
        list_repo=list_repo, push_history_repo=hist_repo
    )
    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        user_repo=user_repo,
        push_history_repo=hist_repo,
        sender_provider=_SenderProvider(sender),
        push_job_queue=queue,
        list_queue_service=list_queue_service,
    )
    from astrbot_plugin_rsshub.src.infrastructure.fetcher import RSSParser

    box = _ContentBox(sample_rss_feed)
    polling = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=sub_repo,
        fetcher_factory=_fetcher_factory(box),
        parser=RSSParser(),
        notification_dispatcher=dispatcher,
        history_entry_limit=100,
    )
    coordinator = ListBatchCoordinator(
        list_repo=list_repo,
        queue_repo=list_repo,
        batch_repo=list_repo,
        renderer=ListBatchRenderer(),
        session_push_queue=queue,
        dispatcher=dispatcher,
        push_history_repo=hist_repo,
    )

    # 1. 首次轮询 bootstrap：建立 entry_hashes，不推送。
    bootstrap_result = await polling.poll_feed_group(feed.id, [sub.id])
    assert bootstrap_result.success is True
    assert bootstrap_result.bootstrap_skipped is True
    assert await list_repo.count_queued(lst.id) == 0

    # 2. 追加新条目 → 再次轮询 → 订阅属于 List → 持久化入队（durably_queued）
    box.content = sample_rss_feed.replace(
        "</channel>",
        "<item><title>New Item</title><link>https://example.com/new</link>"
        "<guid>new-guid-1</guid><description>new content</description></item>"
        "</channel>",
    )
    result = await polling.poll_feed_group(feed.id, [sub.id])
    assert result.success is True
    assert result.new_entries == 1
    assert await list_repo.count_queued(lst.id) == 1

    # 3. 批次触发 → 渲染标题链接 → 发送
    await coordinator.tick()
    batches = await list_repo.list_batches(lst.id)
    assert len(batches) == 1
    assert batches[0].state == "success"
    assert batches[0].item_count == 1

    # 3. 分片发送到 sender
    assert len(sender.messages) == 1
    assert "# Tech" in sender.messages[0]

    # 4. 队列项置为 sent，水位已推进（entry_hashes 含该条目）
    assert await list_repo.count_queued(lst.id) == 0
    feed_after = await feed_repo.get_by_id(feed.id)
    assert feed_after is not None and feed_after.entry_hashes

    # 5. push_history 为 success
    histories = await hist_repo.get_by_sub(sub.id, status="success")
    assert len(histories) == 1

    await get_database().close()
