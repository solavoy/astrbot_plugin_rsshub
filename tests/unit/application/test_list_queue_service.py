"""List 持久化入队服务单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_rsshub.src.application.services.list_queue_service import (
    ListQueueService,
)
from astrbot_plugin_rsshub.src.domain.entities.list_entities import (
    ListEntity,
    ListQueueItem,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.database import get_database
from astrbot_plugin_rsshub.src.infrastructure.persistence.list_repository_impl import (
    ListRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.push_history_repository_impl import (
    PushHistoryRepositoryImpl,
)


@pytest.mark.asyncio
async def test_enqueue_durable_writes_history_and_queue_atomically(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    service = ListQueueService(
        list_repo=repo, push_history_repo=PushHistoryRepositoryImpl()
    )
    result = await service.enqueue_durable(
        list_id=lst.id,
        sub_id=1,
        feed_id=1,
        entry_key="k",
        entry_guid="guid-1",
        entry_title="T",
        entry_link="https://e.com/1",
        feed_title="F",
        feed_link="",
        markdown_content="正文",
        media_items=[],
        user_id="u1",
        target_session="s1",
        platform_name="telegram",
    )
    assert result.durably_queued is True and result.history_id is not None
    assert await repo.count_queued(lst.id) == 1
    # push_history 应存在且为 pending，并写入 entry_guid 供成功去重使用
    history = await PushHistoryRepositoryImpl().get_by_id(result.history_id)
    assert history is not None and history.status == "pending"
    assert history.entry_guid == "guid-1"
    await get_database().close()


@pytest.mark.asyncio
async def test_enqueue_durable_fails_without_target_session(temp_db_path):
    service = ListQueueService(list_repo=MagicMock(), push_history_repo=MagicMock())
    result = await service.enqueue_durable(
        list_id=1,
        sub_id=1,
        feed_id=1,
        entry_key="k",
        entry_title="",
        entry_link="",
        feed_title="",
        feed_link="",
        markdown_content="",
        media_items=[],
        user_id="u1",
        target_session="",
        platform_name="telegram",
    )
    assert result.durably_queued is False


@pytest.mark.asyncio
async def test_enqueue_durable_is_idempotent_on_duplicate_key(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    service = ListQueueService(
        list_repo=repo, push_history_repo=PushHistoryRepositoryImpl()
    )
    first = await service.enqueue_durable(
        list_id=lst.id,
        sub_id=1,
        feed_id=1,
        entry_key="k",
        entry_title="T",
        entry_link="https://e.com/1",
        feed_title="F",
        feed_link="",
        markdown_content="正文",
        media_items=[],
        user_id="u1",
        target_session="s1",
        platform_name="telegram",
    )
    assert first.durably_queued is True
    second = await service.enqueue_durable(
        list_id=lst.id,
        sub_id=1,
        feed_id=1,
        entry_key="k",
        entry_title="T2",
        entry_link="https://e.com/2",
        feed_title="F",
        feed_link="",
        markdown_content="正文2",
        media_items=[],
        user_id="u1",
        target_session="s1",
        platform_name="telegram",
    )
    assert second.durably_queued is False  # 唯一约束：不重复入队
    assert second.already_queued is True  # 视为规则性幂等，不计硬失败
    assert await repo.count_queued(lst.id) == 1
    await get_database().close()


@pytest.mark.asyncio
async def test_filter_for_list_combines_sub_and_list_keywords(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(
            name="Tech",
            user_id="u1",
            target_session="s1",
            platform_name="telegram",
            include_keywords=["python"],
            exclude_keywords=["广告"],
        )
    )
    service = ListQueueService(
        list_repo=repo, push_history_repo=PushHistoryRepositoryImpl()
    )
    sub = MagicMock()
    sub.include_keywords = ["python"]
    sub.exclude_keywords = ["二手"]
    # 订阅屏蔽词命中
    r1 = service.filter_for_list(
        sub, lst, effective_content="Python 二手教程", title="T"
    )
    assert not r1.allowed
    # List 屏蔽词命中
    r2 = service.filter_for_list(
        sub, lst, effective_content="Python 广告", title="T"
    )
    assert not r2.allowed
    # 正常命中
    r3 = service.filter_for_list(
        sub, lst, effective_content="Python 入门指南", title="T"
    )
    assert r3.allowed
    await get_database().close()


@pytest.mark.asyncio
async def test_cleanup_subscription_cleans_queue_and_marks_pending_history_skipped(temp_db_path):
    """删除订阅：清理未发送队列项，并把 pending 历史标为 skipped。"""
    from astrbot_plugin_rsshub.src.infrastructure.persistence.push_history_repository_impl import (
        PushHistoryRepositoryImpl,
    )

    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    hist_repo = PushHistoryRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    service = ListQueueService(list_repo=repo, push_history_repo=hist_repo)
    result = await service.enqueue_durable(
        list_id=lst.id,
        sub_id=1,
        feed_id=1,
        entry_key="k",
        entry_title="T",
        entry_link="https://e.com/1",
        feed_title="F",
        feed_link="",
        markdown_content="正文",
        media_items=[],
        user_id="u1",
        target_session="s1",
        platform_name="telegram",
    )
    assert result.durably_queued is True
    assert await repo.count_queued(lst.id) == 1

    await service.cleanup_subscription(1)
    assert await repo.count_queued(lst.id) == 0
    history = await hist_repo.get_by_id(result.history_id)
    assert history is not None and history.status == "skipped"
    await get_database().close()


@pytest.mark.asyncio
async def test_cleanup_user_removes_lists_and_queue_items(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    hist_repo = PushHistoryRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    service = ListQueueService(list_repo=repo, push_history_repo=hist_repo)
    await service.enqueue_durable(
        list_id=lst.id,
        sub_id=1,
        feed_id=1,
        entry_key="k",
        entry_title="T",
        entry_link="https://e.com/1",
        feed_title="F",
        feed_link="",
        markdown_content="正文",
        media_items=[],
        user_id="u1",
        target_session="s1",
        platform_name="telegram",
    )
    assert await repo.count_queued(lst.id) == 1
    await service.cleanup_user("u1")
    assert await repo.count_queued(lst.id) == 0
    assert await repo.get_list(lst.id) is None  # List 已删除
    await get_database().close()


@pytest.mark.asyncio
async def test_deactivate_list_rejects_new_entries_but_keeps_queue(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    hist_repo = PushHistoryRepositoryImpl()
    lst = await repo.save_list(
        ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    )
    service = ListQueueService(list_repo=repo, push_history_repo=hist_repo)
    first = await service.enqueue_durable(
        list_id=lst.id, sub_id=1, feed_id=1, entry_key="k1",
        entry_title="T", entry_link="https://e.com/1", feed_title="F",
        feed_link="", markdown_content="正文", media_items=[],
        user_id="u1", target_session="s1", platform_name="telegram",
    )
    assert first.durably_queued is True
    # 停用后：拒绝新条目，已入队项保留
    await service.deactivate_list(lst.id)
    second = await service.enqueue_durable(
        list_id=lst.id, sub_id=1, feed_id=1, entry_key="k2",
        entry_title="T2", entry_link="https://e.com/2", feed_title="F",
        feed_link="", markdown_content="正文2", media_items=[],
        user_id="u1", target_session="s1", platform_name="telegram",
    )
    assert second.durably_queued is False
    assert "list disabled" in second.error
    assert await repo.count_queued(lst.id) == 1  # 已入队项保留
    # 清空队列：queued/claimed 置为 skipped
    cleared = await service.clear_queue(lst.id)
    assert cleared == 1
    assert await repo.count_queued(lst.id) == 0
    await get_database().close()
