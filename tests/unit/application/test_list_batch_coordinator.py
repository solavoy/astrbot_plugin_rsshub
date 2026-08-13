"""List 批次协调器与渲染器单元测试。"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from astrbot_plugin_rsshub.src.application.services.list_batch_coordinator import (
    ListBatchCoordinator,
)
from astrbot_plugin_rsshub.src.application.services.list_batch_renderer import (
    ListBatchRenderer,
)
from astrbot_plugin_rsshub.src.application.services.session_push_queue import (
    SessionPushQueue,
)
from astrbot_plugin_rsshub.src.domain.entities.list_entities import (
    ListBatch,
    ListBatchPart,
    ListEntity,
    ListQueueItem,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.database import get_database
from astrbot_plugin_rsshub.src.infrastructure.persistence.list_repository_impl import (
    ListRepositoryImpl,
)


def _make_item(list_id, idx, *, title="T", link="https://e.com/x", feed_title="Feed") -> ListQueueItem:
    return ListQueueItem(
        list_id=list_id,
        sub_id=1,
        feed_id=1,
        push_history_id=100 + idx,
        entry_key=f"k{idx}",
        entry_title=f"{title}{idx}",
        entry_link=f"{link}{idx}",
        feed_title=f"{feed_title}{idx % 2}",
        feed_link="https://f.com",
        markdown_content=f"正文{idx}",
    )


def test_render_title_link_groups_by_feed():
    items = [_make_item(1, 0), _make_item(1, 1), _make_item(1, 2)]
    parts = ListBatchRenderer().render_title_link(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram"),
        items,
    )
    assert len(parts) == 1
    part = parts[0]
    assert part.kind == "aggregate"
    assert "# Tech" in part.markdown_content
    assert "## Feed0" in part.markdown_content and "## Feed1" in part.markdown_content
    # URL 按 MarkdownV2 转义（`.` -> `\.`）
    assert "https://e\\.com/x0" in part.markdown_content


def test_render_full_split_creates_entry_parts():
    items = [_make_item(1, 0), _make_item(1, 1)]
    parts = ListBatchRenderer().render_full_split(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram"),
        items,
    )
    assert len(parts) == 2
    assert [p.kind for p in parts] == ["entry", "entry"]
    assert parts[0].markdown_content == "正文0"
    assert parts[1].markdown_content == "正文1"


def test_render_full_aggregate_joins_items():
    items = [_make_item(1, 0), _make_item(1, 1)]
    parts = ListBatchRenderer().render_full_aggregate(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram"),
        items,
    )
    assert len(parts) == 1
    text = parts[0].markdown_content
    assert "## T0" in text and "## T1" in text
    assert "查看原文" in text


@pytest.mark.asyncio
async def test_tick_creates_full_batches_for_25_items(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(
            name="Tech",
            user_id="u1",
            target_session="s1",
            platform_name="telegram",
            batch_size=10,
            content_mode="title_link",
        )
    )
    for i in range(25):
        await repo.enqueue_item(_make_item(lst.id, i))
    queue = SessionPushQueue()
    coordinator = ListBatchCoordinator(
        list_repo=repo,
        queue_repo=repo,
        batch_repo=repo,
        renderer=ListBatchRenderer(),
        session_push_queue=queue,
    )
    await coordinator.tick()
    batches = await repo.list_batches(lst.id, limit=50)
    assert len(batches) == 2  # 10 + 10 完整批次，剩余 5 未入批
    assert batches[0].item_count == 10 and batches[1].item_count == 10
    assert await repo.count_queued(lst.id) == 5
    await get_database().close()


@pytest.mark.asyncio
async def test_tick_creates_timeout_batch_for_partial_items(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(
            name="Tech",
            user_id="u1",
            target_session="s1",
            platform_name="telegram",
            batch_size=10,
            max_wait_minutes=0,  # 立即超时
            content_mode="title_link",
        )
    )
    await repo.enqueue_item(_make_item(lst.id, 0))
    coordinator = ListBatchCoordinator(
        list_repo=repo,
        queue_repo=repo,
        batch_repo=repo,
        renderer=ListBatchRenderer(),
        session_push_queue=SessionPushQueue(),
    )
    await coordinator.tick()
    batches = await repo.list_batches(lst.id, limit=50)
    assert len(batches) == 1
    assert batches[0].item_count == 1
    await get_database().close()


@pytest.mark.asyncio
async def test_recover_marks_interrupted_batches_failed(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    batch = await repo.create_batch(ListBatch(list_id=lst.id, state="sending", item_count=2))
    coordinator = ListBatchCoordinator(
        list_repo=repo,
        queue_repo=repo,
        batch_repo=repo,
        renderer=ListBatchRenderer(),
        session_push_queue=SessionPushQueue(),
    )
    await coordinator.recover()
    recovered = await repo.get_batch(batch.id)
    assert recovered.state == "failed"
    assert "recovered" in recovered.fail_reason
    await get_database().close()


@pytest.mark.asyncio
async def test_concurrent_tick_only_claims_once(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(
            name="Tech",
            user_id="u1",
            target_session="s1",
            platform_name="telegram",
            batch_size=3,
            content_mode="title_link",
        )
    )
    for i in range(3):
        await repo.enqueue_item(_make_item(lst.id, i))
    coordinator = ListBatchCoordinator(
        list_repo=repo,
        queue_repo=repo,
        batch_repo=repo,
        renderer=ListBatchRenderer(),
        session_push_queue=SessionPushQueue(),
    )
    await asyncio.gather(coordinator.tick(), coordinator.tick(), coordinator.tick())
    batches = await repo.list_batches(lst.id, limit=50)
    assert len(batches) == 1
    await get_database().close()


class _FakeDispatcher:
    """记录发送内容的假 Dispatcher。"""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_to_session(self, **kwargs) -> dict:
        self.sent.append(str(kwargs.get("content") or ""))
        return {"ok": True}

    async def send_to_session_now(self, **kwargs) -> dict:
        self.sent.append(str(kwargs.get("content") or ""))
        return {"ok": True}


@pytest.mark.asyncio
async def test_retry_batch_resends_only_failed_parts(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    item1 = await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=1, entry_key="a")
    )
    item2 = await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=2, entry_key="b")
    )
    batch = await repo.create_batch(ListBatch(list_id=lst.id, item_count=2))
    await repo.claim_items_for_batch(lst.id, batch.id, limit=10)
    parts = [
        ListBatchPart(batch_id=batch.id, sequence=0, kind="entry", markdown_content="ok", state="success"),
        ListBatchPart(batch_id=batch.id, sequence=1, kind="entry", markdown_content="bad", state="failed", fail_reason="boom"),
    ]
    await repo.insert_parts(parts)
    await repo.insert_part_items([(parts[0].id, item1.id), (parts[1].id, item2.id)])
    batch.state = "failed"
    batch.fail_reason = "some parts failed"
    await repo.update_batch(batch)

    fake = _FakeDispatcher()
    coordinator = ListBatchCoordinator(
        list_repo=repo,
        queue_repo=repo,
        batch_repo=repo,
        renderer=ListBatchRenderer(),
        session_push_queue=SessionPushQueue(),
        dispatcher=fake,
    )
    await coordinator.retry_batch(batch.id)
    # 重试只重发失败分片
    assert fake.sent == ["bad"]
    parts_after = await repo.get_parts(batch.id)
    assert parts_after[0].state == "success"
    assert parts_after[1].state == "success"
    batch_after = await repo.get_batch(batch.id)
    assert batch_after.state == "success"
    # 队列项应从 failed 回到 sent（mark_batch_items_sent 匹配 claimed+failed）
    item1_after = await repo.get_queue_item(item1.id)
    item2_after = await repo.get_queue_item(item2.id)
    assert item1_after.state == "sent"
    assert item2_after.state == "sent"
    await get_database().close()


@pytest.mark.asyncio
async def test_summary_failure_keeps_batch_success(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(
            name="Tech",
            user_id="u1",
            target_session="s1",
            platform_name="telegram",
            ai_summary_enabled=True,
            max_wait_minutes=0,  # 立即超时，单条目也触发批次
            content_mode="title_link",
        )
    )
    await repo.enqueue_item(
        ListQueueItem(
            list_id=lst.id, sub_id=1, feed_id=1, push_history_id=1,
            entry_key="k", entry_title="T", entry_link="https://e.com/1",
        )
    )

    class _FailProvider:
        async def summarize_batch(self, **kwargs):
            raise RuntimeError("boom")

    coordinator = ListBatchCoordinator(
        list_repo=repo,
        queue_repo=repo,
        batch_repo=repo,
        renderer=ListBatchRenderer(),
        session_push_queue=SessionPushQueue(),
        summary_provider=_FailProvider(),
        dispatcher=_FakeDispatcher(),
    )
    await coordinator.tick()
    batches = await repo.list_batches(lst.id)
    assert batches[0].state == "success"
    assert batches[0].summary_status == "failed"
    await get_database().close()


@pytest.mark.asyncio
async def test_summary_success_inserts_summary_part(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(
            name="Tech",
            user_id="u1",
            target_session="s1",
            platform_name="telegram",
            ai_summary_enabled=True,
            ai_summary_prompt="请总结",
            max_wait_minutes=0,  # 立即超时
            content_mode="title_link",
        )
    )
    await repo.enqueue_item(
        ListQueueItem(
            list_id=lst.id, sub_id=1, feed_id=1, push_history_id=1,
            entry_key="k", entry_title="T", entry_link="https://e.com/1",
        )
    )

    class _OkProvider:
        async def summarize_batch(self, *, list_entity, items_title_link, prompt):
            assert prompt == "请总结"
            return "## 总结内容"

    fake = _FakeDispatcher()
    coordinator = ListBatchCoordinator(
        list_repo=repo,
        queue_repo=repo,
        batch_repo=repo,
        renderer=ListBatchRenderer(),
        session_push_queue=SessionPushQueue(),
        summary_provider=_OkProvider(),
        dispatcher=fake,
    )
    await coordinator.tick()
    batches = await repo.list_batches(lst.id)
    assert batches[0].state == "success"
    assert batches[0].summary_status == "success"
    assert "总结内容" in batches[0].summary_markdown
    # AI 总结分片应实际发送到用户
    assert any("总结内容" in msg for msg in fake.sent)
    parts = await repo.get_parts(batches[0].id)
    assert any(p.kind == "summary" for p in parts)
    await get_database().close()


def test_render_escapes_special_characters_in_title_and_link():
    items = [
        ListQueueItem(
            list_id=1, sub_id=1, feed_id=1, push_history_id=1, entry_key="k",
            entry_title="My *bold* [x]", entry_link="https://en.wikipedia.org/wiki/Foo_(bar)",
            feed_title="Feed", feed_link="https://f.com", markdown_content="正文",
        )
    ]
    part = ListBatchRenderer().render_title_link(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram"),
        items,
    )[0]
    assert "My \\*bold\\* \\[x\\]" in part.markdown_content
    # URL 中 `(` `)` 转义为 `\(` `\)`
    assert "Foo\\_\\(bar\\)" in part.markdown_content


@pytest.mark.asyncio
async def test_concurrent_flush_only_creates_one_batch(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    await repo.enqueue_item(_make_item(lst.id, 0))
    coordinator = ListBatchCoordinator(
        list_repo=repo,
        queue_repo=repo,
        batch_repo=repo,
        renderer=ListBatchRenderer(),
        session_push_queue=SessionPushQueue(),
    )
    results = await asyncio.gather(
        coordinator.flush_list(lst.id),
        coordinator.flush_list(lst.id),
    )
    # 只有一个调用 claim 到条目，另一个在锁内读到 0 返回
    assert sorted(results) == [0, 1]
    batches = await repo.list_batches(lst.id, limit=50)
    assert len(batches) == 1
    assert batches[0].state != "failed"  # 无幽灵失败批次
    await get_database().close()


@pytest.mark.asyncio
async def test_recover_also_handles_ready_batches(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    item = await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=1, entry_key="a")
    )
    ready_batch = await repo.create_batch(ListBatch(list_id=lst.id, state="ready", item_count=1))
    await repo.claim_items_for_batch(lst.id, ready_batch.id, limit=10)
    coordinator = ListBatchCoordinator(
        list_repo=repo,
        queue_repo=repo,
        batch_repo=repo,
        renderer=ListBatchRenderer(),
        session_push_queue=SessionPushQueue(),
    )
    await coordinator.recover()
    recovered = await repo.get_batch(ready_batch.id)
    assert recovered.state == "failed"
    # 队列项回退为 queued，可被下一轮重新 claim
    assert await repo.count_queued(lst.id) == 1
    await get_database().close()
