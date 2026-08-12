"""List 批次仓储实现单元测试。"""

from __future__ import annotations

import pytest

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


@pytest.mark.asyncio
async def test_enqueue_respects_unique_key_and_claim_transitions(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    item1 = await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=11, entry_key="k")
    )
    assert item1.id is not None
    dup = await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=12, entry_key="k")
    )
    assert dup.id is None or dup.id == item1.id  # 唯一约束，不产生第二条
    assert await repo.count_queued(lst.id) == 1
    batch = await repo.create_batch(ListBatch(list_id=lst.id, item_count=1))
    claimed = await repo.claim_items_for_batch(lst.id, batch.id, limit=10)
    assert claimed == 1
    sent = await repo.mark_batch_items_sent(batch.id)
    assert sent == 1
    assert await repo.count_queued(lst.id) == 0
    await get_database().close()


@pytest.mark.asyncio
async def test_get_lists_by_scope_and_active(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    await repo.save_list(
        ListEntity(name="News", user_id="u1", target_session="s1", platform_name="telegram", state=0)
    )
    scoped = await repo.get_lists_by_scope("u1", "s1", "telegram")
    assert [l.name for l in scoped] == ["Tech", "News"]
    active = await repo.get_active_lists()
    assert [l.name for l in active] == ["Tech"]
    got = await repo.get_list(lst.id)
    assert got is not None and got.name == "Tech"
    await get_database().close()


@pytest.mark.asyncio
async def test_oldest_queued_at_and_skipped_and_delete_by_sub(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=11, entry_key="a")
    )
    await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=2, feed_id=1, push_history_id=12, entry_key="b")
    )
    assert await repo.count_queued(lst.id) == 2
    oldest = await repo.oldest_queued_at(lst.id)
    assert oldest is not None
    items = await repo.get_queued_items(lst.id)
    assert len(items) == 2 and items[0].entry_key == "a"
    # 订阅删除清理
    deleted = await repo.delete_by_sub(1)
    assert deleted >= 1
    assert await repo.count_queued(lst.id) == 1
    await get_database().close()


@pytest.mark.asyncio
async def test_batches_and_parts_persistence(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    item = await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=11, entry_key="k")
    )
    batch = await repo.create_batch(ListBatch(list_id=lst.id, item_count=1))
    claimed = await repo.claim_items_for_batch(lst.id, batch.id, limit=10)
    assert claimed == 1
    parts = [
        ListBatchPart(batch_id=batch.id, sequence=0, kind="entry", markdown_content="正文"),
        ListBatchPart(batch_id=batch.id, sequence=1, kind="summary", markdown_content="总结"),
    ]
    await repo.insert_parts(parts)
    await repo.insert_part_items([(parts[0].id, item.id)])
    loaded = await repo.get_parts(batch.id)
    assert len(loaded) == 2
    ids = await repo.get_part_item_ids(parts[0].id)
    assert ids == [item.id]
    loaded[0].state = "success"
    await repo.update_part(loaded[0])
    updated = await repo.get_parts(batch.id)
    assert updated[0].state == "success"
    batches = await repo.list_batches(lst.id, limit=5)
    assert len(batches) == 1 and batches[0].item_count == 1
    await get_database().close()


@pytest.mark.asyncio
async def test_failed_batch_retry_semantics(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    item = await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=11, entry_key="k")
    )
    batch = await repo.create_batch(ListBatch(list_id=lst.id, item_count=1))
    await repo.claim_items_for_batch(lst.id, batch.id, limit=10)
    parts = [ListBatchPart(batch_id=batch.id, sequence=0, kind="entry", markdown_content="x")]
    await repo.insert_parts(parts)
    await repo.insert_part_items([(parts[0].id, item.id)])
    # 分片失败 → 批次失败
    parts[0].state = "failed"
    parts[0].fail_reason = "boom"
    await repo.update_part(parts[0])
    batch.state = "failed"
    await repo.update_batch(batch)
    failed = await repo.get_batch(batch.id)
    assert failed is not None and failed.state == "failed"
    await get_database().close()


@pytest.mark.asyncio
async def test_mark_items_skipped_and_delete_by_list(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=11, entry_key="a")
    )
    await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=2, feed_id=1, push_history_id=12, entry_key="b")
    )
    n = await repo.mark_items_skipped(lst.id, reason="cleared by user")
    assert n == 2
    assert await repo.count_queued(lst.id) == 0
    # 再次入队后按 List 删除
    await repo.enqueue_item(
        ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=13, entry_key="c")
    )
    deleted = await repo.delete_by_list(lst.id)
    assert deleted >= 1
    await get_database().close()
