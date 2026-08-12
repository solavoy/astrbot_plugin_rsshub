"""List 仓库接口

定义 List 逻辑集合、队列项、批次与分片的持久化操作规范。
具体实现由基础设施层提供。
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..entities.list_entities import (
    ListBatch,
    ListBatchPart,
    ListEntity,
    ListQueueItem,
)


class ListRepository(Protocol):
    """List 仓库接口"""

    # ---- lists ----
    async def get_list(self, list_id: int) -> ListEntity | None:
        """按 ID 获取 List。"""
        ...

    async def get_lists_by_scope(
        self, user_id: str, target_session: str, platform_name: str
    ) -> list[ListEntity]:
        """按用户/会话/平台范围获取 List。"""
        ...

    async def get_lists_by_user(self, user_id: str) -> list[ListEntity]:
        """获取指定用户的全部 List。"""
        ...

    async def get_all_lists(self) -> list[ListEntity]:
        """获取全部 List（含停用）。"""
        ...

    async def get_active_lists(self) -> list[ListEntity]:
        """获取全部启用状态的 List。"""
        ...

    async def save_list(self, entity: ListEntity) -> ListEntity:
        """保存 List（新增或更新），返回带 ID 的实体。"""
        ...

    async def delete_list(self, list_id: int) -> None:
        """删除 List。"""
        ...

    # ---- queue items ----
    async def enqueue_item(self, item: ListQueueItem) -> ListQueueItem:
        """幂等入队：unique(list_id, sub_id, entry_key) 已存在时返回已有项。"""
        ...

    async def count_queued(self, list_id: int) -> int:
        """统计排队中的队列项数量。"""
        ...

    async def get_queued_items(
        self, list_id: int, limit: int | None = None
    ) -> list[ListQueueItem]:
        """获取排队中的队列项（按 queued_at 升序）。"""
        ...

    async def get_batch_items(self, batch_id: int) -> list[ListQueueItem]:
        """获取已 claim 到某批次的队列项（按 queued_at 升序）。"""
        ...

    async def get_queue_item(self, item_id: int) -> ListQueueItem | None:
        """按 ID 获取队列项。"""
        ...

    async def oldest_queued_at(self, list_id: int) -> datetime | None:
        """获取最早排队项的入队时间。"""
        ...

    async def claim_items_for_batch(
        self, list_id: int, batch_id: int, limit: int
    ) -> int:
        """把 queued 置为 claimed 并绑定 batch_id，返回受影响行数。"""
        ...

    async def mark_batch_items_sent(self, batch_id: int) -> int:
        """把 claimed 置为 sent。"""
        ...

    async def mark_batch_items_failed(self, batch_id: int, reason: str) -> int:
        """把 claimed 置为 failed 并记录原因。"""
        ...

    async def mark_items_skipped(self, list_id: int, reason: str) -> int:
        """把 queued/claimed 置为 skipped 并清空 batch_id。"""
        ...

    async def delete_by_sub(self, sub_id: int) -> int:
        """删除指定订阅的未发送队列项。"""
        ...

    async def delete_by_feed(self, feed_id: int) -> int:
        """删除指定 Feed 的未发送队列项。"""
        ...

    async def delete_by_list(self, list_id: int) -> int:
        """删除指定 List 的全部队列项。"""
        ...

    # ---- batches ----
    async def create_batch(self, batch: ListBatch) -> ListBatch:
        """创建批次，返回带 ID 的实体。"""
        ...

    async def get_batch(self, batch_id: int) -> ListBatch | None:
        """按 ID 获取批次。"""
        ...

    async def update_batch(self, batch: ListBatch) -> None:
        """更新批次。"""
        ...

    async def list_batches(self, list_id: int, limit: int = 20) -> list[ListBatch]:
        """列出 List 的批次（按创建时间倒序）。"""
        ...

    async def list_incomplete_batches(self, limit: int = 100) -> list[ListBatch]:
        """列出所有 preparing/sending 的未完成批次（启动恢复用）。"""
        ...

    async def requeue_batch_items(self, batch_id: int) -> int:
        """把某批次的 claimed 队列项回退为 queued，返回受影响行数。"""
        ...

    # ---- batch parts ----
    async def insert_parts(self, parts: list[ListBatchPart]) -> None:
        """批量插入分片。"""
        ...

    async def get_parts(self, batch_id: int) -> list[ListBatchPart]:
        """获取批次的全部按顺序排列的分片。"""
        ...

    async def update_part(self, part: ListBatchPart) -> None:
        """更新分片。"""
        ...

    async def insert_part_items(self, pairs: list[tuple[int, int]]) -> None:
        """批量插入分片-队列项关联 (part_id, queue_item_id)。"""
        ...

    async def get_part_item_ids(self, batch_part_id: int) -> list[int]:
        """获取分片关联的队列项 ID 列表。"""
        ...
