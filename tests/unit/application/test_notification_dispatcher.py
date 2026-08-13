from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.application.ports import SendResult
from astrbot_plugin_rsshub.src.application.services.notification_dispatcher import (
    NotificationDispatcher,
    SendTarget,
    append_media_links_to_text,
    infer_media_type,
    normalize_media_items,
    strip_appended_media_links_from_text,
)
from astrbot_plugin_rsshub.src.application.services.session_push_queue import (
    PushJobResult,
    SessionPushQueue,
)
from astrbot_plugin_rsshub.src.domain.entities.content_types import (
    EntryContentContext,
    LayoutFragment,
    build_generated_media_url,
)
from astrbot_plugin_rsshub.src.domain.entities.push_history import PushHistory
from astrbot_plugin_rsshub.src.domain.entities.subscription import Subscription
from astrbot_plugin_rsshub.src.domain.entities.user import User


class FakeSender:
    def __init__(self, result: SendResult | None = None) -> None:
        self.result = result or SendResult(ok=True)
        self.requests = []

    async def send_to_user(self, request, context=None):
        self.requests.append((request, context))
        return self.result


class FakeSenderProvider:
    def __init__(self, sender: FakeSender) -> None:
        self.sender = sender

    def get(self, platform_name: str | None):
        return self.sender


@pytest.mark.asyncio
async def test_dispatch_sends_via_injected_sender_provider():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )

    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history
    user_repo = AsyncMock()
    user_repo.get_or_create.return_value = User(id="user-1")

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        user_repo=user_repo,
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    user_repo.get_or_create.assert_awaited_once_with("user-1")
    assert len(sender.requests) == 1
    request, context = sender.requests[0]
    assert request.session_id == "telegram:Group:1"
    assert request.message == "content"
    assert context.platform_name == "telegram"
    assert history_repo.save.await_count == 2
    first_saved = history_repo.save.await_args_list[0].args[0]
    assert first_saved.media_urls is None


@pytest.mark.asyncio
async def test_dispatch_formats_markdown_only_for_telegram():
    """自动按平台：Telegram 输出 Markdown 排版，OneBot 保持纯文本。"""
    sender = FakeSender()
    subscriptions = [
        Subscription(
            id=1,
            user_id="user-1",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        Subscription(
            id=2,
            user_id="user-2",
            feed_id=10,
            platform_name="onebot",
            target_session="onebot:user-2",
        ),
    ]
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = subscriptions
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history
    user_repo = AsyncMock()
    user_repo.get_or_create.side_effect = lambda user_id: User(id=user_id)

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        user_repo=user_repo,
    )

    await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
        raw_entry=EntryContentContext(
            title="title",
            summary="content",
            content="content",
            link="https://example.com/entry",
            author="author",
            feed_title="feed",
            feed_link="https://example.com/feed.xml",
        ),
    )

    assert len(sender.requests) == 2, f"got {len(sender.requests)}: {sender.requests}"
    requests: dict[str, tuple] = {}
    for req, ctx in sender.requests:
        requests[req.session_id] = (req, ctx)

    # Telegram：Markdown 排版 + 渲染标记
    tg_req, tg_ctx = requests["telegram:Group:1"]
    assert "**title**" in tg_req.message
    assert "\n\n---\n\n" in tg_req.message
    assert "via [https://example\\.com/entry](https://example\\.com/entry)" in (
        tg_req.message
    )
    assert tg_ctx.render_markdown is True

    # OneBot：内容统一为 Markdown，渲染标记为 False（由 sender 边界降级）
    ob_req, ob_ctx = requests["onebot:user-2"]
    assert "**title**" in ob_req.message
    assert ob_ctx.render_markdown is False


@pytest.mark.asyncio
async def test_dispatch_non_telegram_marks_render_markdown_false():
    """非 Telegram 平台内容统一为 Markdown，渲染标记为 False（sender 层降级）。"""
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="aiocqhttp",
        target_session="onebot:user-1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
        raw_entry=EntryContentContext(
            title="title",
            summary="content",
            content="content",
            link="https://example.com/entry",
            author="author",
            feed_title="feed",
            feed_link="https://example.com/feed.xml",
        ),
    )

    assert len(sender.requests) == 1
    req, ctx = sender.requests[0]
    assert "**title**" in req.message
    assert "via [https://example\\.com/entry]" in req.message
    assert ctx.render_markdown is False


@pytest.mark.asyncio
async def test_dispatch_cleans_raw_generated_layout_temp_after_fanout(tmp_path: Path):
    sender = FakeSender()
    subscriptions = [
        Subscription(
            id=1,
            user_id="user-1",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        Subscription(
            id=2,
            user_id="user-2",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:2",
        ),
    ]
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = subscriptions
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history
    user_repo = AsyncMock()
    user_repo.get_or_create.side_effect = lambda user_id: User(id=user_id)
    temp_png = tmp_path / "rsshub_table_shared.png"
    temp_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)
    source_id = build_generated_media_url("table", "3" * 64)

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        user_repo=user_repo,
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-table",
        raw_entry=EntryContentContext(
            title="title",
            summary="content",
            content="content",
            link="https://example.com/entry",
            author="",
            feed_title="feed",
            feed_link="https://example.com/feed.xml",
            layout=(
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url=source_id,
                    local_path=str(temp_png),
                ),
            ),
        ),
    )

    assert stats == {"success": 2, "failed": 0, "pending": 0, "skipped": 0}
    assert len(sender.requests) == 2
    assert not temp_png.exists()


@pytest.mark.asyncio
async def test_dispatch_cleans_raw_generated_layout_when_subscription_load_fails(
    tmp_path: Path,
):
    sender = FakeSender()
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.side_effect = RuntimeError("repo unavailable")
    history_repo = AsyncMock()
    temp_png = tmp_path / "rsshub_table_failed_repo.png"
    temp_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)
    source_id = build_generated_media_url("table", "7" * 64)

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    with pytest.raises(RuntimeError, match="repo unavailable"):
        await dispatcher.dispatch_to_feed_subscribers(
            feed_id=10,
            content="content",
            entry_title="title",
            entry_link="https://example.com/entry",
            raw_entry=EntryContentContext(
                title="title",
                summary="content",
                content="content",
                link="https://example.com/entry",
                author="",
                feed_title="feed",
                feed_link="https://example.com/feed.xml",
                layout=(
                    LayoutFragment(
                        kind="image",
                        media_type="image",
                        url=source_id,
                        local_path=str(temp_png),
                    ),
                ),
            ),
        )

    assert not temp_png.exists()


@pytest.mark.asyncio
async def test_dispatch_cleans_processed_generated_layout_when_notify_disabled(
    tmp_path: Path,
):
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    user = User(id="user-1", notify=0)
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    user_repo = AsyncMock()
    user_repo.get_or_create.return_value = user
    history_repo = AsyncMock()
    history_repo.save.side_effect = lambda history: history
    temp_png = tmp_path / "rsshub_table_processed.png"
    temp_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)
    source_id = build_generated_media_url("table", "6" * 64)
    processed_entry = EntryContentContext(
        title="Title",
        summary="Body",
        content="Body",
        link="https://example.com/entry",
        author="",
        feed_title="Feed",
        feed_link="https://example.com/feed.xml",
        layout=(
            LayoutFragment(
                kind="image",
                media_type="image",
                url=source_id,
                local_path=str(temp_png),
            ),
        ),
    )

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        user_repo=user_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        raw_entry=processed_entry,
    )

    assert stats == {"success": 0, "failed": 0, "pending": 0, "skipped": 1}
    assert sender.requests == []
    assert not temp_png.exists()


@pytest.mark.asyncio
async def test_dispatch_guard_skips_already_successful_entry_guid():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = True

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
    )

    assert stats == {"success": 0, "failed": 0, "pending": 0, "skipped": 1}
    assert sender.requests == []
    history_repo.save.assert_awaited_once()
    saved = history_repo.save.await_args.args[0]
    assert saved.status == "skipped"
    assert saved.fail_reason == "dispatch guard: already successful entry_guid"
    assert saved.max_retries == 0
    assert saved.entry_guid == "guid-1"


@pytest.mark.asyncio
async def test_qq_official_degraded_success_is_acked_by_success_guard():
    sender = FakeSender(SendResult(ok=True))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="qq_official",
        target_session="qqofficial:FriendMessage:openid-1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.side_effect = [False, True]
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    first = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content\n媒体原始链接:\nhttps://example.com/huge.jpg",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_urls=["https://example.com/huge.jpg"],
        entry_guid="guid-qq-degraded",
    )
    second = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content\n媒体原始链接:\nhttps://example.com/huge.jpg",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_urls=["https://example.com/huge.jpg"],
        entry_guid="guid-qq-degraded",
    )

    assert first == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    assert second == {"success": 0, "failed": 0, "pending": 0, "skipped": 1}
    assert len(sender.requests) == 1
    success_history = history_repo.save.await_args_list[1].args[0]
    skipped_history = history_repo.save.await_args_list[2].args[0]
    assert success_history.status == "success"
    assert success_history.fail_reason is None
    assert success_history.entry_guid == "guid-qq-degraded"
    assert skipped_history.status == "skipped"
    assert (
        skipped_history.fail_reason == "dispatch guard: already successful entry_guid"
    )


@pytest.mark.asyncio
async def test_dispatch_can_limit_to_selected_subscription_ids():
    sender = FakeSender()
    subs = [
        Subscription(
            id=1,
            user_id="user-1",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        Subscription(
            id=2,
            user_id="user-2",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:2",
        ),
    ]

    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = subs
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
        subscription_ids=[2],
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    assert len(sender.requests) == 1
    assert sender.requests[0][0].session_id == "telegram:Group:2"


@pytest.mark.asyncio
async def test_dispatch_uses_session_queue_for_same_session():
    sender = FakeSender()
    queue = SessionPushQueue()
    subs = [
        Subscription(
            id=1,
            user_id="user-1",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        Subscription(
            id=2,
            user_id="user-2",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
    ]

    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = subs
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        push_job_queue=queue,
        basic_settings=SimpleNamespace(
            failed_queue_capacity=50,
            failed_queue_max_retries=3,
            deduplicate_multi_bot=False,
        ),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
    )

    assert stats == {"success": 2, "failed": 0, "pending": 0, "skipped": 0}
    assert len(sender.requests) == 2
    assert queue.get_current_job("telegram:Group:1") is None


@pytest.mark.asyncio
async def test_send_to_session_returns_cancelled_result_from_queue():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    queue = SessionPushQueue()
    queue.enqueue = AsyncMock(
        return_value=PushJobResult(
            job_id="rss-000123",
            session_id="telegram:Group:1",
            ok=False,
            cancelled=True,
            error="job cancelled",
        )
    )

    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=AsyncMock(),
        sender_provider=FakeSenderProvider(sender),
        push_job_queue=queue,
    )

    result = await dispatcher.send_to_session(
        target=SendTarget(
            user_id=sub.user_id,
            platform_name=sub.platform_name,
            target_session=sub.target_session,
            sub_id=sub.id,
        ),
        content="content",
        media_urls=None,
    )

    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["job_id"] == "rss-000123"
    assert "Cancelled by System or Command" in result["error"]
    assert sender.requests == []


def test_infer_media_type_detects_rsshub_wrapped_video_url():
    url = (
        "https://proxy.example/?url=https%3A%2F%2Fvideo.twimg.com%2Fext_tw_video"
        "%2F123%2Fpu%2Fvid%2Favc1%2F720x1280%2Fclip.mp4%3Ftag%3D14"
    )

    assert infer_media_type(url) == "video"


def test_normalize_media_items_preserves_explicit_video_type_without_extension():
    url = "https://example.com/media/play?id=123"

    assert normalize_media_items(media_items=[("video", url)]) == [("video", url)]


def test_append_media_links_to_text_is_idempotent():
    text = "hello\n媒体原始链接:\nhttps://example.com/a.mp4"

    result = append_media_links_to_text(
        text,
        media_urls=["https://example.com/a.mp4"],
    )

    assert result == text


def test_strip_appended_media_links_from_text_removes_failure_suffix():
    text = "hello\n媒体原始链接:\nhttps://example.com/a.mp4"

    result = strip_appended_media_links_from_text(
        text,
        media_urls=["https://example.com/a.mp4"],
    )

    assert result == "hello"


def test_strip_appended_media_links_from_text_keeps_unrelated_suffix():
    text = "hello\n媒体原始链接:\nhttps://example.com/a.mp4\nhttps://example.com/extra"

    result = strip_appended_media_links_from_text(
        text,
        media_urls=["https://example.com/a.mp4"],
    )

    assert result == text


@pytest.mark.asyncio
async def test_send_to_session_preserves_video_media_type():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=AsyncMock(),
        sender_provider=FakeSenderProvider(sender),
    )
    video_url = "https://example.com/video.mp4?tag=14"

    result = await dispatcher.send_to_session(
        target=SendTarget(
            user_id=sub.user_id,
            platform_name=sub.platform_name,
            target_session=sub.target_session,
            sub_id=sub.id,
        ),
        content="content",
        media_urls=[video_url],
    )

    assert result["ok"] is True
    request, _context = sender.requests[0]
    assert request.media == [("video", video_url)]


@pytest.mark.asyncio
async def test_send_to_session_preserves_explicit_video_media_item():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=AsyncMock(),
        sender_provider=FakeSenderProvider(sender),
    )
    video_url = "https://example.com/media/play?id=123"

    result = await dispatcher.send_to_session(
        target=SendTarget(
            user_id=sub.user_id,
            platform_name=sub.platform_name,
            target_session=sub.target_session,
            sub_id=sub.id,
        ),
        content="content",
        media_urls=[video_url],
        media_items=[("video", video_url)],
    )

    assert result["ok"] is True
    request, _context = sender.requests[0]
    assert request.media == [("video", video_url)]


@pytest.mark.asyncio
async def test_send_to_session_passes_entry_context_to_sender():
    sender = FakeSender()
    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=AsyncMock(),
        sender_provider=FakeSenderProvider(sender),
    )

    result = await dispatcher.send_to_session(
        target=SendTarget(
            user_id="user-1",
            platform_name="telegram",
            target_session="telegram:Group:1",
            sub_id=1,
        ),
        content="content",
        media_urls=None,
        channel_title="Feed",
        channel_link="https://example.com/feed",
        entry_title="Entry title",
        entry_link="https://example.com/post",
    )

    assert result["ok"] is True
    _request, context = sender.requests[0]
    assert context.entry_title == "Entry title"
    assert context.entry_link == "https://example.com/post"


@pytest.mark.asyncio
async def test_dispatch_persists_media_urls_and_appends_links_on_failure():
    sender = FakeSender(SendResult(ok=False, detail="forward failed"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )
    media_url = "https://example.com/video.mp4"

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_urls=[media_url],
    )

    assert stats == {"success": 0, "failed": 0, "pending": 1, "skipped": 0}
    assert history_repo.save.await_count == 2
    first_saved = history_repo.save.await_args_list[0].args[0]
    second_saved = history_repo.save.await_args_list[1].args[0]
    assert first_saved.media_urls == [media_url]
    assert second_saved.media_urls == [media_url]
    assert "媒体原始链接:" in second_saved.content
    assert media_url in second_saved.content


@pytest.mark.asyncio
async def test_dispatch_feed_entry_persists_raw_xml_in_history():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
        raw_entry=EntryContentContext(
            title="title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            raw_xml="<item><title>title</title></item>",
        ),
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    first_saved = history_repo.save.await_args_list[0].args[0]
    assert first_saved.raw_xml == "<item><title>title</title></item>"


@pytest.mark.asyncio
async def test_dispatch_with_raw_entry_keeps_cleaned_content_when_not_processed():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        # 非 telegram 平台，避免 Markdown 干扰"内容清洗"断言
        platform_name="onebot",
        target_session="onebot:user-1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    clean_content = (
        "[ -50 Squad ] #エンドフィールド #WakeofSpringCC\n\n"
        "via https://x.com/NoUgrad/status/2057138522574971385 | "
        "Twitter following timeline (author: NoUGraD)"
    )
    html_body = (
        "[ -50 Squad ]<br />#エンドフィールド #WakeofSpringCC<br />"
        '<img src="https://example.com/image.jpg" />'
        '<div class="rsshub-quote"><video src="https://example.com/video.mp4">'
        "</video></div>"
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content=clean_content,
        entry_title="[ -50 Squad ] #エンドフィールド #WakeofSpringCC",
        entry_link="https://x.com/NoUgrad/status/2057138522574971385",
        entry_guid="guid-1",
        raw_entry=EntryContentContext(
            title="[ -50 Squad ] #エンドフィールド #WakeofSpringCC",
            summary=html_body,
            content=html_body,
            link="https://x.com/NoUgrad/status/2057138522574971385",
            author="NoUGraD",
            feed_title="Twitter following timeline",
            feed_link="https://rsshub.example/twitter",
            raw_xml="<item><description>raw</description></item>",
        ),
        media_items=[
            ("image", "https://example.com/image.jpg"),
            ("video", "https://example.com/video.mp4"),
        ],
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    first_saved = history_repo.save.await_args_list[0].args[0]
    assert first_saved.raw_xml == "<item><description>raw</description></item>"
    assert "<br" not in first_saved.content
    assert "<img" not in first_saved.content
    assert "<video" not in first_saved.content
    # 内容统一为规范 Markdown：标题加粗，HTML 标签不泄漏
    assert "**\\[ \\-50 Squad \\] \\#エンドフィールド" in first_saved.content
    assert "Twitter following timeline" in first_saved.content
    request, _context = sender.requests[0]
    assert request.message == first_saved.content


@pytest.mark.asyncio
async def test_dispatch_formats_raw_entry_with_effective_options_from_subscription():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        # 非 telegram 平台，避免 Markdown 干扰"生效选项"断言
        platform_name="onebot",
        target_session="onebot:user-1",
        length_limit=4,
        display_title=-1,
        display_author=-1,
        display_via=-2,
        display_media=-1,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
        raw_entry=EntryContentContext(
            title="Title",
            summary="abcdef<br>&lt;img src=&quot;https://example.com/a.jpg&quot;&gt;",
            content="abcdef<br>&lt;img src=&quot;https://example.com/a.jpg&quot;&gt;",
            link="https://example.com/entry",
            author="Author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
        ),
        media_items=[("image", "https://example.com/a.jpg")],
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    first_saved = history_repo.save.await_args_list[0].args[0]
    assert first_saved.content == r"a\.\.\."
    assert first_saved.media_urls is None
    request, _context = sender.requests[0]
    assert request.message == r"a\.\.\."
    assert request.media is None


@pytest.mark.asyncio
async def test_dispatch_ignores_layout_and_formats_markdown_with_length_limit():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        length_limit=8,
        style=2,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        entry_guid="guid-original-limit",
        raw_entry=EntryContentContext(
            title="Title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            layout=(
                LayoutFragment(kind="text", text="abcdefghij"),
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/a.jpg",
                ),
                LayoutFragment(kind="text", text="tail"),
                LayoutFragment(
                    kind="file",
                    media_type="file",
                    url="https://example.com/report.pdf",
                    name="report.pdf",
                ),
            ),
        ),
        media_items=[
            ("image", "https://example.com/a.jpg"),
            ("file", "https://example.com/report.pdf"),
        ],
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    request, context = sender.requests[0]
    # original 排版已移除：layout 只承载 generated 媒体映射，不参与正文排版。
    assert request.layout is not None
    assert "**Title**" in request.message
    assert request.media == [
        ("image", "https://example.com/a.jpg"),
        ("file", "https://example.com/report.pdf"),
    ]


@pytest.mark.asyncio
async def test_dispatch_keeps_original_layout_text_when_length_limit_disabled():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        length_limit=0,
        style=2,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        entry_guid="guid-original-no-limit",
        raw_entry=EntryContentContext(
            title="Title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            layout=(LayoutFragment(kind="text", text="abcdefghij"),),
        ),
    )

    request, _context = sender.requests[0]
    # original 排版已移除：layout 不参与正文，正文为规范 Markdown。
    assert request.layout is not None
    assert "abcdefghij" not in request.message


@pytest.mark.asyncio
async def test_dispatch_clears_original_layout_when_media_hidden():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        display_media=-1,
        style=2,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        entry_guid="guid-original-media-hidden",
        raw_entry=EntryContentContext(
            title="Title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            layout=(
                LayoutFragment(kind="text", text="lead"),
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/a.jpg",
                ),
            ),
        ),
        media_items=[("image", "https://example.com/a.jpg")],
    )

    request, _context = sender.requests[0]
    assert request.media is None  # display_media 关闭：媒体被抑制
    assert request.layout is not None  # layout 仍承载 generated 映射，但无媒体可发


@pytest.mark.asyncio
async def test_dispatch_link_only_clears_original_layout():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        send_mode=-1,
        style=2,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        entry_guid="guid-original-link-only",
        raw_entry=EntryContentContext(
            title="Title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            layout=(
                LayoutFragment(kind="text", text="lead"),
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/a.jpg",
                ),
            ),
        ),
        media_items=[("image", "https://example.com/a.jpg")],
    )

    request, _context = sender.requests[0]
    assert request.message == "Title\nhttps://example.com/entry"
    assert request.media is None  # link_only：媒体被抑制
    assert request.layout is not None  # layout 承载 generated 映射，不参与正文


@pytest.mark.asyncio
async def test_dispatch_inherits_effective_options_from_user():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    user = User(id="user-1", notify=0)
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    user_repo = AsyncMock()
    user_repo.get_or_create.return_value = user
    history_repo = AsyncMock()

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        user_repo=user_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        raw_entry=EntryContentContext(
            title="Title",
            summary="Body",
            content="Body",
            link="https://example.com/entry",
            author="Author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
        ),
    )

    assert stats == {"success": 0, "failed": 0, "pending": 0, "skipped": 1}
    assert sender.requests == []
    history_repo.save.assert_awaited_once()
    saved = history_repo.save.await_args.args[0]
    assert saved.status == "skipped"
    assert saved.fail_reason == "notify disabled"
    assert saved.max_retries == 0


@pytest.mark.asyncio
async def test_dispatch_failure_uses_configured_retry_limit_and_capacity():
    sender = FakeSender(SendResult(ok=False, detail="forward failed"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.count_retryable_failures = AsyncMock(return_value=1)
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        basic_settings=SimpleNamespace(
            failed_queue_capacity=2,
            failed_queue_max_retries=7,
            deduplicate_multi_bot=True,
        ),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
    )

    assert stats == {"success": 0, "failed": 0, "pending": 1, "skipped": 0}
    first_saved = history_repo.save.await_args_list[0].args[0]
    second_saved = history_repo.save.await_args_list[1].args[0]
    assert first_saved.max_retries == 7
    assert second_saved.max_retries == 7


@pytest.mark.asyncio
async def test_dispatch_failure_disables_retry_when_capacity_full():
    sender = FakeSender(SendResult(ok=False, detail="forward failed"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.count_retryable_failures = AsyncMock(return_value=2)
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        basic_settings=SimpleNamespace(
            failed_queue_capacity=2,
            failed_queue_max_retries=7,
            deduplicate_multi_bot=True,
        ),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
    )

    assert stats == {"success": 0, "failed": 1, "pending": 0, "skipped": 0}
    second_saved = history_repo.save.await_args_list[1].args[0]
    assert second_saved.max_retries == 0


@pytest.mark.asyncio
async def test_dispatch_same_session_equivalent_payload_deduplicates_to_smallest_sub_id():
    sender = FakeSender()
    subs = [
        Subscription(
            id=2,
            user_id="user-2",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        Subscription(
            id=1,
            user_id="user-1",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
    ]
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = subs
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        basic_settings=SimpleNamespace(
            failed_queue_capacity=50,
            failed_queue_max_retries=3,
            deduplicate_multi_bot=True,
        ),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="same-content",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_urls=["https://example.com/a.jpg"],
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 1}
    assert len(sender.requests) == 1
    saved_histories = [call.args[0] for call in history_repo.save.await_args_list]
    skipped = [item for item in saved_histories if item.status == "skipped"]
    assert len(skipped) == 1
    assert skipped[0].sub_id == 2
    assert skipped[0].fail_reason == "multi-bot dedup: reused sub_id=1"


@pytest.mark.asyncio
async def test_dispatch_same_session_different_payload_does_not_deduplicate():
    sender = FakeSender()
    subs = [
        Subscription(
            id=1,
            user_id="user-1",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
            send_mode=0,
        ),
        Subscription(
            id=2,
            user_id="user-2",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
            send_mode=-1,
        ),
    ]
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = subs
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        basic_settings=SimpleNamespace(
            failed_queue_capacity=50,
            failed_queue_max_retries=3,
            deduplicate_multi_bot=True,
        ),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="same-content",
        entry_title="title",
        entry_link="https://example.com/entry",
    )

    assert stats == {"success": 2, "failed": 0, "pending": 0, "skipped": 0}
    assert len(sender.requests) == 2


@pytest.mark.asyncio
async def test_dispatch_pending_retries_marks_cancelled_history_failed():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=99,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        status="retrying",
        retry_count=1,
        max_retries=3,
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    queue = SessionPushQueue()
    queue.enqueue = AsyncMock(
        return_value=PushJobResult(
            job_id="rss-000456",
            session_id="telegram:Group:1",
            ok=False,
            cancelled=True,
            error="job cancelled",
        )
    )

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        push_job_queue=queue,
    )

    stats = await dispatcher.dispatch_pending_retries(limit=10)

    assert stats == {"success": 1, "failed": 0, "skipped": 0}
    assert history.status == "stopped"
    assert history.max_retries == 0
    assert "Cancelled by System or Command" in (history.fail_reason or "")
    history_repo.save.assert_awaited_once_with(history)


@pytest.mark.asyncio
async def test_dispatch_pending_retries_marks_successful_retry_success():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=100,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="retry content\n媒体原始链接:\nhttps://example.com/video.mp4",
        media_urls=["https://example.com/video.mp4"],
        entry_title="title",
        entry_link="https://example.com/entry",
        status="retrying",
        retry_count=1,
        max_retries=3,
        fail_reason="未知错误",
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_pending_retries(limit=5)

    assert stats == {"success": 1, "failed": 0, "skipped": 0}
    assert history.status == "success"
    assert history.retry_count == 1
    assert history.fail_reason is None
    assert history.content == "retry content"
    assert len(sender.requests) == 1
    assert sender.requests[0][0].message == "retry content"
    assert sender.requests[0][0].media == [("video", "https://example.com/video.mp4")]
    history_repo.get_and_mark_retrying.assert_awaited_once_with(5)
    history_repo.save.assert_awaited_once_with(history)


@pytest.mark.asyncio
async def test_retry_push_history_once_updates_same_record_on_failure():
    sender = FakeSender(SendResult(ok=False, transient=True, detail="upload failed"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=104,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="old content",
        media_urls=["https://example.com/image.jpg"],
        entry_title="title",
        entry_link="https://example.com/entry",
        status="success",
        retry_count=0,
        max_retries=3,
    ).mark_success()
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_by_id.return_value = history
    saved_snapshots = []

    async def save_history(value):
        saved_snapshots.append((value.id, value.status, value.content))
        return value

    history_repo.save.side_effect = save_history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    result = await dispatcher.retry_push_history_once(104)

    assert result["ok"] is False
    retry_history = result["history"]
    assert retry_history is history
    assert retry_history.id == 104
    assert retry_history.status == "failed"
    assert retry_history.retry_count == 0
    assert retry_history.max_retries == 0
    assert retry_history.fail_reason == "upload failed"
    assert retry_history.completed_at is not None
    assert "媒体原始链接:" in retry_history.content
    assert "https://example.com/image.jpg" in retry_history.content
    assert len(sender.requests) == 1
    assert sender.requests[0][0].message == "old content"
    assert sender.requests[0][0].media == [("image", "https://example.com/image.jpg")]
    history_repo.get_by_id.assert_awaited_once_with(104)
    assert history_repo.save.await_count == 2
    assert saved_snapshots[0] == (104, "retrying", "old content")
    assert saved_snapshots[1][0] == 104
    assert saved_snapshots[1][1] == "failed"


@pytest.mark.asyncio
async def test_retry_push_history_once_updates_same_record_on_success():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=105,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="retry content\n媒体原始链接:\nhttps://example.com/video.mp4",
        media_urls=["https://example.com/video.mp4"],
        entry_title="title",
        entry_link="https://example.com/entry",
        status="failed",
        retry_count=3,
        max_retries=3,
        fail_reason="previous failure",
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_by_id.return_value = history
    saved_snapshots = []

    async def save_history(value):
        saved_snapshots.append((value.id, value.status, value.content))
        return value

    history_repo.save.side_effect = save_history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    result = await dispatcher.retry_push_history_once(105)

    assert result["ok"] is True
    retry_history = result["history"]
    assert retry_history is history
    assert retry_history.id == 105
    assert retry_history.status == "success"
    assert retry_history.retry_count == 0
    assert retry_history.max_retries == 0
    assert retry_history.fail_reason is None
    assert retry_history.content == "retry content"
    assert len(sender.requests) == 1
    assert sender.requests[0][0].message == "retry content"
    assert sender.requests[0][0].media == [("video", "https://example.com/video.mp4")]
    history_repo.get_by_id.assert_awaited_once_with(105)
    assert history_repo.save.await_count == 2
    assert saved_snapshots[0] == (105, "retrying", "retry content")
    assert saved_snapshots[1] == (105, "success", "retry content")


@pytest.mark.asyncio
async def test_dispatch_pending_retries_records_recoverable_failure():
    sender = FakeSender(SendResult(ok=False, transient=True, detail="timeout"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=101,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="retry content",
        entry_title="title",
        entry_link="https://example.com/entry",
        status="retrying",
        retry_count=1,
        max_retries=3,
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_pending_retries(limit=5)

    assert stats == {"success": 0, "failed": 1, "skipped": 0}
    assert history.status == "failed"
    assert history.retry_count == 2
    assert history.max_retries == 3
    assert history.fail_reason == "timeout"
    history_repo.save.assert_awaited_once_with(history)


@pytest.mark.asyncio
async def test_dispatch_pending_retries_stops_unrecoverable_failure():
    sender = FakeSender(SendResult(ok=False, detail="permission denied"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=102,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="retry content",
        entry_title="title",
        entry_link="https://example.com/entry",
        status="retrying",
        retry_count=1,
        max_retries=3,
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_pending_retries(limit=5)

    assert stats == {"success": 0, "failed": 1, "skipped": 0}
    assert history.status == "failed"
    assert history.retry_count == 1
    assert history.max_retries == 0
    assert history.fail_reason == "permission denied"
    history_repo.save.assert_awaited_once_with(history)


@pytest.mark.asyncio
async def test_dispatch_pending_retries_skips_disabled_subscription():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        state=0,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=103,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="retry content",
        entry_title="title",
        entry_link="https://example.com/entry",
        status="retrying",
        retry_count=1,
        max_retries=3,
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_pending_retries(limit=5)

    assert stats == {"success": 0, "failed": 0, "skipped": 1}
    assert history.status == "failed"
    assert history.fail_reason == "Subscription not available"
    assert sender.requests == []
    history_repo.save.assert_awaited_once_with(history)


@pytest.mark.asyncio
async def test_dispatch_agent_entry_deduplicates_only_success_records():
    sender = FakeSender()
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = True
    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    result = await dispatcher.dispatch_agent_entry(
        source_key="agent:test",
        target=SendTarget(
            user_id="user-1",
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        content="content",
        raw_xml="<entry><p>Hello</p></entry>",
        entry_title="title",
        entry_guid="guid-1",
    )

    assert result["ok"] is True
    assert result["deduplicated"] is True
    history_repo.save.assert_not_awaited()
    assert sender.requests == []


@pytest.mark.asyncio
async def test_dispatch_agent_entry_persists_raw_xml_in_history():
    sender = FakeSender()
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history
    user_repo = AsyncMock()
    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        user_repo=user_repo,
    )

    result = await dispatcher.dispatch_agent_entry(
        source_key="agent:test",
        target=SendTarget(
            user_id="user-1",
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        content="content",
        raw_xml="<entry><p>Hello</p></entry>",
        entry_title="title",
        entry_guid="guid-raw",
    )

    assert result["ok"] is True
    user_repo.get_or_create.assert_awaited_once_with("user-1")
    first_saved = history_repo.save.await_args_list[0].args[0]
    assert first_saved.raw_xml == "<entry><p>Hello</p></entry>"


@pytest.mark.asyncio
async def test_dispatch_pending_retries_reuses_agent_history_without_subscription():
    sender = FakeSender()
    history = PushHistory(
        id=104,
        sub_id=None,
        user_id="user-1",
        feed_id=None,
        source_type="agent",
        source_key="agent:test",
        content="retry content\n媒体原始链接:\nhttps://example.com/video.mp4",
        media_urls=["https://example.com/video.mp4"],
        entry_title="title",
        entry_link="https://example.com/entry",
        platform_name="telegram",
        target_session="telegram:Group:1",
        status="retrying",
        retry_count=1,
        max_retries=3,
    )

    sub_repo = AsyncMock()
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_pending_retries(limit=5)

    assert stats == {"success": 1, "failed": 0, "skipped": 0}
    sub_repo.get_by_id.assert_not_awaited()
    assert history.status == "success"
    assert sender.requests[0][0].session_id == "telegram:Group:1"


@pytest.mark.asyncio
async def test_dispatch_auto_mode_prefers_telegraph_when_multiple_media(monkeypatch):
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        send_mode=0,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    called: dict[str, object] = {}

    async def fake_send(*args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs
        return {
            "ok": True,
            "used_telegraph": True,
            "fallback_native": False,
        }

    monkeypatch.setattr(dispatcher, "_send_to_session", fake_send, raising=False)

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_items=[
            ("image", "https://example.com/1.jpg"),
            ("video", "https://example.com/2.mp4"),
        ],
    )

    assert stats["success"] == 1
    assert called["kwargs"]["media_items"] == [
        ("image", "https://example.com/1.jpg"),
        ("video", "https://example.com/2.mp4"),
    ]
    assert called["kwargs"]["send_mode"] == 0


@pytest.mark.asyncio
async def test_dispatch_telegraph_failure_falls_back_to_native_send(monkeypatch):
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        send_mode=0,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    async def fake_send(*args, **kwargs):
        return {
            "ok": True,
            "used_telegraph": False,
            "telegraph_error": "create page failed",
            "fallback_native": True,
        }

    monkeypatch.setattr(dispatcher, "_send_to_session", fake_send, raising=False)

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_items=[
            ("image", "https://example.com/1.jpg"),
            ("image", "https://example.com/2.jpg"),
        ],
    )

    assert stats["success"] == 1


@pytest.mark.asyncio
async def test_dispatch_routes_list_subscription_to_durable_enqueue():
    """订阅属于启用 List 时走持久化入队，不即时发送。"""
    from astrbot_plugin_rsshub.src.domain.entities.list_entities import ListEntity

    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        list_id=5,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history
    user_repo = AsyncMock()
    user_repo.get_or_create.return_value = User(id="user-1")

    list_queue = AsyncMock()
    list_queue.load_list.return_value = ListEntity(
        id=5, name="Tech", user_id="user-1",
        target_session="telegram:Group:1", platform_name="telegram",
    )
    list_queue.filter_for_list = MagicMock(
        return_value=SimpleNamespace(allowed=True, reason="")
    )
    list_queue.enqueue_durable.return_value = SimpleNamespace(
        durably_queued=True, history_id=99, error=""
    )

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        user_repo=user_repo,
        list_queue_service=list_queue,
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
    )

    assert stats["durably_queued"] == 1
    assert stats["success"] == 0
    assert len(sender.requests) == 0  # 未即时发送
    list_queue.enqueue_durable.assert_awaited_once()
    call_kwargs = list_queue.enqueue_durable.call_args.kwargs
    assert call_kwargs["list_id"] == 5
    assert call_kwargs["entry_key"] == "guid-1"
    assert call_kwargs["entry_guid"] == "guid-1"


@pytest.mark.asyncio
async def test_dispatch_list_subscription_filtered_writes_skipped():
    """List 命中过滤规则时写 skipped 历史并跳过发送。"""
    from astrbot_plugin_rsshub.src.domain.entities.list_entities import ListEntity

    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        list_id=5,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history
    user_repo = AsyncMock()
    user_repo.get_or_create.return_value = User(id="user-1")

    list_queue = AsyncMock()
    list_queue.load_list.return_value = ListEntity(
        id=5, name="Tech", user_id="user-1",
        target_session="telegram:Group:1", platform_name="telegram",
    )
    list_queue.filter_for_list = MagicMock(
        return_value=SimpleNamespace(
            allowed=False, reason="filtered: subscription exclude keyword"
        )
    )

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        user_repo=user_repo,
        list_queue_service=list_queue,
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
    )

    assert stats["skipped"] == 1
    assert len(sender.requests) == 0
    list_queue.enqueue_durable.assert_not_awaited()
    # skipped 历史写入
    skipped_saves = [
        call.args[0] for call in history_repo.save.await_args_list
    ]
    assert any(h.status == "skipped" for h in skipped_saves)


@pytest.mark.asyncio
async def test_dispatch_list_subscription_without_list_queue_service_sends():
    """未装配 ListQueueService 时，list_id 订阅照常即时发送（向后兼容）。"""
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        list_id=5,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history
    user_repo = AsyncMock()
    user_repo.get_or_create.return_value = User(id="user-1")

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        user_repo=user_repo,
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
    )

    assert stats["success"] == 1
    assert len(sender.requests) == 1


@pytest.mark.asyncio
async def test_dispatch_list_subscription_disabled_list_skips_new_entries():
    """List 停用：不新入队，新条目按规则性 skipped 推进水位。"""
    from astrbot_plugin_rsshub.src.domain.entities.list_entities import ListEntity

    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        list_id=5,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history
    user_repo = AsyncMock()
    user_repo.get_or_create.return_value = User(id="user-1")

    list_queue = AsyncMock()
    list_queue.load_list.return_value = ListEntity(
        id=5, name="Tech", user_id="user-1",
        target_session="telegram:Group:1", platform_name="telegram",
        state=0,  # 停用
    )

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        user_repo=user_repo,
        list_queue_service=list_queue,
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
    )

    assert stats["skipped"] == 1
    assert stats["success"] == 0
    assert len(sender.requests) == 0
    list_queue.enqueue_durable.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_list_subscription_respects_display_media_off():
    """List 订阅 display_media 关闭时入队不带媒体。"""
    from astrbot_plugin_rsshub.src.domain.entities.list_entities import ListEntity

    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        list_id=5,
        display_media=-1,  # 禁用媒体
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history
    user_repo = AsyncMock()
    user_repo.get_or_create.return_value = User(id="user-1")

    list_queue = AsyncMock()
    list_queue.load_list.return_value = ListEntity(
        id=5, name="Tech", user_id="user-1",
        target_session="telegram:Group:1", platform_name="telegram",
    )
    list_queue.filter_for_list = MagicMock(
        return_value=SimpleNamespace(allowed=True, reason="")
    )
    list_queue.enqueue_durable.return_value = SimpleNamespace(
        durably_queued=True, history_id=99, error="", already_queued=False
    )

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        user_repo=user_repo,
        list_queue_service=list_queue,
    )

    await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
        media_items=[("image", "https://example.com/pic.jpg")],
    )

    call_kwargs = list_queue.enqueue_durable.call_args.kwargs
    assert call_kwargs["media_items"] == []  # 媒体被抑制
