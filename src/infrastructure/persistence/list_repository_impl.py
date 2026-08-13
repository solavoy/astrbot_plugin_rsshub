"""List 仓库实现

基于 SQLModel/SQLAlchemy 实现 ListRepository 接口。
负责 List、队列项、批次与分片的持久化。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlmodel import asc, desc, select

from ...domain.entities.list_entities import (
    ListBatch,
    ListBatchPart,
    ListEntity,
    ListQueueItem,
)
from ..utils import get_logger
from .database import get_database
from .models import (
    ListBatchORM,
    ListBatchPartItemORM,
    ListBatchPartORM,
    ListORM,
    ListQueueItemORM,
)

logger = get_logger()


def _media_to_json(
    media_items: tuple[tuple[str, str], ...] | list[tuple[str, str]] | None,
) -> list[list[str]] | None:
    if not media_items:
        return None
    return [list(item) for item in media_items]


def _media_from_json(value: Any) -> tuple[tuple[str, str], ...]:
    if not value:
        return ()
    result: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            result.append((str(item[0]), str(item[1])))
    return tuple(result)


class ListRepositoryImpl:
    """List 仓库实现类"""

    # ============================ lists ============================

    async def get_list(self, list_id: int) -> ListEntity | None:
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(ListORM, list_id)
            return self._list_to_entity(orm) if orm else None

    async def get_lists_by_scope(
        self, user_id: str, target_session: str, platform_name: str
    ) -> list[ListEntity]:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(ListORM)
                .where(
                    ListORM.user_id == user_id,
                    ListORM.target_session == target_session,
                    ListORM.platform_name == platform_name,
                )
                .order_by(asc(ListORM.id))
            )
            result = await session.execute(stmt)
            return [self._list_to_entity(orm) for orm in result.scalars().all()]

    async def get_lists_by_user(self, user_id: str) -> list[ListEntity]:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(ListORM)
                .where(ListORM.user_id == user_id)
                .order_by(asc(ListORM.id))
            )
            result = await session.execute(stmt)
            return [self._list_to_entity(orm) for orm in result.scalars().all()]

    async def get_all_lists(self) -> list[ListEntity]:
        db = get_database()
        async with db.get_session() as session:
            stmt = select(ListORM).order_by(asc(ListORM.id))
            result = await session.execute(stmt)
            return [self._list_to_entity(orm) for orm in result.scalars().all()]

    async def get_active_lists(self) -> list[ListEntity]:
        db = get_database()
        async with db.get_session() as session:
            stmt = select(ListORM).where(ListORM.state == 1).order_by(asc(ListORM.id))
            result = await session.execute(stmt)
            return [self._list_to_entity(orm) for orm in result.scalars().all()]

    async def save_list(self, entity: ListEntity) -> ListEntity:
        db = get_database()
        async with db.get_session() as session:
            if entity.id is None:
                orm = self._list_to_orm(entity)
                session.add(orm)
                await session.commit()
                await session.refresh(orm)
                return self._list_to_entity(orm)
            orm = await session.get(ListORM, entity.id)
            if orm is None:
                raise ValueError(f"List {entity.id} 不存在")
            orm.name = entity.name
            orm.state = entity.state
            orm.batch_size = entity.batch_size
            orm.max_wait_minutes = entity.max_wait_minutes
            orm.content_mode = entity.content_mode
            orm.full_delivery_mode = entity.full_delivery_mode
            orm.ai_summary_enabled = entity.ai_summary_enabled
            orm.ai_summary_prompt = entity.ai_summary_prompt
            orm.include_keywords = entity.include_keywords or None
            orm.exclude_keywords = entity.exclude_keywords or None
            orm.updated_at = datetime.now(timezone.utc)
            session.add(orm)
            await session.commit()
            await session.refresh(orm)
            return self._list_to_entity(orm)

    async def delete_list(self, list_id: int) -> None:
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(ListORM, list_id)
            if orm:
                await session.delete(orm)
                await session.commit()

    # ============================ queue items ============================

    async def enqueue_item(self, item: ListQueueItem) -> ListQueueItem:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(ListQueueItemORM)
                .where(
                    ListQueueItemORM.list_id == item.list_id,
                    ListQueueItemORM.sub_id == item.sub_id,
                    ListQueueItemORM.entry_key == item.entry_key,
                )
                .limit(1)
            )
            existing = (await session.execute(stmt)).scalars().first()
            if existing is not None:
                return self._queue_to_entity(existing)
            orm = self._queue_to_orm(item)
            session.add(orm)
            await session.commit()
            await session.refresh(orm)
            return self._queue_to_entity(orm)

    async def count_queued(self, list_id: int) -> int:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(ListQueueItemORM.id)
                .where(
                    ListQueueItemORM.list_id == list_id,
                    ListQueueItemORM.state == "queued",
                )
                .execution_options(synchronize_session=False)
            )
            result = await session.execute(stmt)
            return len(result.all())

    async def get_queued_items(
        self, list_id: int, limit: int | None = None
    ) -> list[ListQueueItem]:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(ListQueueItemORM)
                .where(
                    ListQueueItemORM.list_id == list_id,
                    ListQueueItemORM.state == "queued",
                )
                .order_by(asc(ListQueueItemORM.queued_at), asc(ListQueueItemORM.id))
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return [self._queue_to_entity(orm) for orm in result.scalars().all()]

    async def get_queue_item(self, item_id: int) -> ListQueueItem | None:
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(ListQueueItemORM, item_id)
            return self._queue_to_entity(orm) if orm else None

    async def get_batch_items(self, batch_id: int) -> list[ListQueueItem]:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(ListQueueItemORM)
                .where(ListQueueItemORM.batch_id == batch_id)
                .order_by(asc(ListQueueItemORM.queued_at), asc(ListQueueItemORM.id))
            )
            result = await session.execute(stmt)
            return [self._queue_to_entity(orm) for orm in result.scalars().all()]

    async def oldest_queued_at(self, list_id: int) -> datetime | None:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(ListQueueItemORM.queued_at)
                .where(
                    ListQueueItemORM.list_id == list_id,
                    ListQueueItemORM.state == "queued",
                )
                .order_by(asc(ListQueueItemORM.queued_at))
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def claim_items_for_batch(
        self, list_id: int, batch_id: int, limit: int
    ) -> int:
        db = get_database()
        async with db.get_session() as session:
            # SQLite UPDATE ... ORDER BY ... LIMIT 需 3.33+；这里改用子查询选择 ID，
            # 再按 state='queued' 原子更新，避免并发下重复 claim。
            ids_stmt = (
                select(ListQueueItemORM.id)
                .where(
                    ListQueueItemORM.list_id == list_id,
                    ListQueueItemORM.state == "queued",
                )
                .order_by(asc(ListQueueItemORM.queued_at), asc(ListQueueItemORM.id))
                .limit(limit)
            )
            ids = list((await session.execute(ids_stmt)).scalars().all())
            if not ids:
                return 0
            stmt = (
                update(ListQueueItemORM)
                .where(
                    ListQueueItemORM.id.in_(ids),
                    ListQueueItemORM.state == "queued",
                )
                .values(state="claimed", batch_id=batch_id)
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def mark_batch_items_sent(self, batch_id: int) -> int:
        """把批次内已发送的队列项置为 sent。

        重试路径下队列项可能处于 failed（首轮部分失败后 mark_batch_items_failed
        已把 claimed 全部置 failed）；重试成功时同样应回到 sent，因此匹配
        claimed 与 failed 两种状态。
        """
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                update(ListQueueItemORM)
                .where(
                    ListQueueItemORM.batch_id == batch_id,
                    ListQueueItemORM.state.in_(("claimed", "failed")),
                )
                .values(state="sent")
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def mark_batch_items_failed(self, batch_id: int, reason: str) -> int:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                update(ListQueueItemORM)
                .where(
                    ListQueueItemORM.batch_id == batch_id,
                    ListQueueItemORM.state == "claimed",
                )
                .values(state="failed")
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def mark_items_skipped(self, list_id: int, reason: str) -> int:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                update(ListQueueItemORM)
                .where(
                    ListQueueItemORM.list_id == list_id,
                    ListQueueItemORM.state.in_(("queued", "claimed")),
                )
                .values(state="skipped", batch_id=None)
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def delete_by_sub(self, sub_id: int) -> int:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                update(ListQueueItemORM)
                .where(
                    ListQueueItemORM.sub_id == sub_id,
                    ListQueueItemORM.state.in_(("queued", "claimed")),
                )
                .values(state="skipped")
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def delete_by_feed(self, feed_id: int) -> int:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                update(ListQueueItemORM)
                .where(
                    ListQueueItemORM.feed_id == feed_id,
                    ListQueueItemORM.state.in_(("queued", "claimed")),
                )
                .values(state="skipped")
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def delete_by_list(self, list_id: int) -> int:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                update(ListQueueItemORM)
                .where(
                    ListQueueItemORM.list_id == list_id,
                    ListQueueItemORM.state.in_(("queued", "claimed")),
                )
                .values(state="skipped")
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    # ============================ batches ============================

    async def create_batch(self, batch: ListBatch) -> ListBatch:
        db = get_database()
        async with db.get_session() as session:
            orm = ListBatchORM(
                list_id=batch.list_id,
                state=batch.state,
                item_count=batch.item_count,
                summary_markdown=batch.summary_markdown,
                summary_status=batch.summary_status,
                fail_reason=batch.fail_reason,
            )
            session.add(orm)
            await session.commit()
            await session.refresh(orm)
            return self._batch_to_entity(orm)

    async def get_batch(self, batch_id: int) -> ListBatch | None:
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(ListBatchORM, batch_id)
            return self._batch_to_entity(orm) if orm else None

    async def update_batch(self, batch: ListBatch) -> None:
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(ListBatchORM, batch.id)
            if orm is None:
                return
            orm.state = batch.state
            orm.item_count = batch.item_count
            orm.summary_markdown = batch.summary_markdown
            orm.summary_status = batch.summary_status
            orm.fail_reason = batch.fail_reason
            orm.started_at = batch.started_at
            orm.completed_at = batch.completed_at
            session.add(orm)
            await session.commit()

    async def list_batches(self, list_id: int, limit: int = 20) -> list[ListBatch]:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(ListBatchORM)
                .where(ListBatchORM.list_id == list_id)
                .order_by(desc(ListBatchORM.id))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [self._batch_to_entity(orm) for orm in result.scalars().all()]

    async def list_incomplete_batches(self, limit: int = 100) -> list[ListBatch]:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(ListBatchORM)
                .where(ListBatchORM.state.in_(("preparing", "ready", "sending")))
                .order_by(asc(ListBatchORM.id))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [self._batch_to_entity(orm) for orm in result.scalars().all()]

    async def requeue_batch_items(self, batch_id: int) -> int:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                update(ListQueueItemORM)
                .where(
                    ListQueueItemORM.batch_id == batch_id,
                    ListQueueItemORM.state == "claimed",
                )
                .values(state="queued", batch_id=None)
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    # ============================ batch parts ============================

    async def insert_parts(self, parts: list[ListBatchPart]) -> None:
        db = get_database()
        async with db.get_session() as session:
            orms = [
                ListBatchPartORM(
                    batch_id=part.batch_id,
                    sequence=part.sequence,
                    kind=part.kind,
                    markdown_content=part.markdown_content,
                    media_items=_media_to_json(part.media_items),
                    state=part.state,
                    fail_reason=part.fail_reason,
                )
                for part in parts
            ]
            for orm in orms:
                session.add(orm)
            await session.commit()
            for orm, part in zip(orms, parts):
                await session.refresh(orm)
                part.id = orm.id

    async def get_parts(self, batch_id: int) -> list[ListBatchPart]:
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(ListBatchPartORM)
                .where(ListBatchPartORM.batch_id == batch_id)
                .order_by(asc(ListBatchPartORM.sequence))
            )
            result = await session.execute(stmt)
            return [self._part_to_entity(orm) for orm in result.scalars().all()]

    async def update_part(self, part: ListBatchPart) -> None:
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(ListBatchPartORM, part.id)
            if orm is None:
                return
            orm.state = part.state
            orm.fail_reason = part.fail_reason
            orm.sent_at = part.sent_at
            orm.markdown_content = part.markdown_content
            session.add(orm)
            await session.commit()

    async def insert_part_items(self, pairs: list[tuple[int, int]]) -> None:
        if not pairs:
            return
        db = get_database()
        async with db.get_session() as session:
            for part_id, queue_item_id in pairs:
                session.add(
                    ListBatchPartItemORM(
                        batch_part_id=part_id, queue_item_id=queue_item_id
                    )
                )
            await session.commit()

    async def get_part_item_ids(self, batch_part_id: int) -> list[int]:
        db = get_database()
        async with db.get_session() as session:
            stmt = select(ListBatchPartItemORM.queue_item_id).where(
                ListBatchPartItemORM.batch_part_id == batch_part_id
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ============================ mappers ============================

    @staticmethod
    def _list_to_entity(orm: ListORM) -> ListEntity:
        return ListEntity(
            id=orm.id,
            name=orm.name,
            user_id=orm.user_id,
            target_session=orm.target_session,
            platform_name=orm.platform_name,
            state=orm.state,
            batch_size=orm.batch_size,
            max_wait_minutes=orm.max_wait_minutes,
            content_mode=orm.content_mode,
            full_delivery_mode=orm.full_delivery_mode,
            ai_summary_enabled=bool(orm.ai_summary_enabled),
            ai_summary_prompt=orm.ai_summary_prompt or "",
            include_keywords=list(orm.include_keywords or []),
            exclude_keywords=list(orm.exclude_keywords or []),
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _list_to_orm(entity: ListEntity) -> ListORM:
        return ListORM(
            id=entity.id,
            name=entity.name,
            user_id=entity.user_id,
            target_session=entity.target_session,
            platform_name=entity.platform_name,
            state=entity.state,
            batch_size=entity.batch_size,
            max_wait_minutes=entity.max_wait_minutes,
            content_mode=entity.content_mode,
            full_delivery_mode=entity.full_delivery_mode,
            ai_summary_enabled=entity.ai_summary_enabled,
            ai_summary_prompt=entity.ai_summary_prompt,
            include_keywords=entity.include_keywords or None,
            exclude_keywords=entity.exclude_keywords or None,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _queue_to_entity(orm: ListQueueItemORM) -> ListQueueItem:
        return ListQueueItem(
            id=orm.id,
            list_id=orm.list_id,
            sub_id=orm.sub_id,
            feed_id=orm.feed_id,
            push_history_id=orm.push_history_id,
            entry_key=orm.entry_key,
            entry_title=orm.entry_title or "",
            entry_link=orm.entry_link or "",
            feed_title=orm.feed_title or "",
            feed_link=orm.feed_link or "",
            markdown_content=orm.markdown_content or "",
            media_items=_media_from_json(orm.media_items),
            queued_at=orm.queued_at,
            batch_id=orm.batch_id,
            state=orm.state,
        )

    @staticmethod
    def _queue_to_orm(item: ListQueueItem) -> ListQueueItemORM:
        return ListQueueItemORM(
            id=item.id,
            list_id=item.list_id,
            sub_id=item.sub_id,
            feed_id=item.feed_id,
            push_history_id=item.push_history_id,
            entry_key=item.entry_key,
            entry_title=item.entry_title,
            entry_link=item.entry_link,
            feed_title=item.feed_title,
            feed_link=item.feed_link,
            markdown_content=item.markdown_content,
            media_items=_media_to_json(item.media_items),
            queued_at=item.queued_at,
            batch_id=item.batch_id,
            state=item.state,
        )

    @staticmethod
    def _batch_to_entity(orm: ListBatchORM) -> ListBatch:
        return ListBatch(
            id=orm.id,
            list_id=orm.list_id,
            state=orm.state,
            item_count=orm.item_count,
            summary_markdown=orm.summary_markdown,
            summary_status=orm.summary_status,
            fail_reason=orm.fail_reason,
            created_at=orm.created_at,
            started_at=orm.started_at,
            completed_at=orm.completed_at,
        )

    @staticmethod
    def _part_to_entity(orm: ListBatchPartORM) -> ListBatchPart:
        return ListBatchPart(
            id=orm.id,
            batch_id=orm.batch_id,
            sequence=orm.sequence,
            kind=orm.kind,
            markdown_content=orm.markdown_content,
            media_items=_media_from_json(orm.media_items),
            state=orm.state,
            fail_reason=orm.fail_reason,
            sent_at=orm.sent_at,
        )


def get_list_repository() -> ListRepositoryImpl:
    """获取 List 仓库实例。"""
    return ListRepositoryImpl()
